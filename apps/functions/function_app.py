"""The event-driven part of the live pipeline: two Cosmos DB change-feed triggers.

    simulator job ──▶ Cosmos `events` ──(change feed)──▶ interpret ──▶ Cosmos `moments` ──(change feed)──▶ dispatch ──▶ Brain ──▶ Cosmos `overlays`

* ``interpret``  runs the match's documents through the interpreter (stateless: it replays the match from the store, which the interpreter's
                 determinism makes safe) and stores the moments it finds and the overlays that need no model.
* ``dispatch``   asks the Brain to write the narrative overlays for new moments (the fast path: Editor, one model call per viewer cohort, Verifier).

Both are idempotent, so the at-least-once delivery of a change feed (and a Brain that was asleep for the first attempt) cannot duplicate anything.
The Functions use the identity the app runs as for Cosmos DB (no keys): ``COSMOS__accountEndpoint`` / ``COSMOS__credential`` / ``COSMOS__clientId``
configure the triggers, ``COSMOS_ENDPOINT`` and ``AZURE_CLIENT_ID`` the store.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import azure.functions as func

os.environ.setdefault("MATCHMIND_DATA", str(Path(__file__).parent / "data"))

from matchmind.live.pipeline import interpret  # noqa: E402
from matchmind.live.store import CosmosLiveStore  # noqa: E402

app = func.FunctionApp()
_store: CosmosLiveStore | None = None


def store() -> CosmosLiveStore:
    global _store
    if _store is None:
        from azure.identity import ManagedIdentityCredential

        _store = CosmosLiveStore(os.environ["COSMOS_ENDPOINT"], credential=ManagedIdentityCredential(client_id=os.environ.get("AZURE_CLIENT_ID")))
    return _store


@app.function_name("interpret")
@app.cosmos_db_trigger(
    arg_name="docs", database_name="matchmind", container_name="events", connection="COSMOS",
    lease_container_name="leases", lease_container_prefix="interpret-", create_lease_container_if_not_exists=False,
    feed_poll_delay=500, max_items_per_invocation=500,
)
def interpret_events(docs: func.DocumentList) -> None:
    t0 = time.monotonic()
    for match_id in sorted({d["matchId"] for d in docs}):
        out = interpret(store(), match_id)
        logging.info("interpret %s: %s documents, %s moments (%s new), %s new overlays, finished=%s, %.1f s", match_id, out.get("documents"), out.get("moments"), len(out.get("newMoments", [])), out.get("newOverlays"), out.get("finished"), time.monotonic() - t0)


def _post_beats(match_id: str, moment_ids: list[str], attempts: int = 4) -> dict:
    """Ask the Brain for the narrative overlays. The Brain scales to zero, so the first attempt may wait out a cold start; later ones back off."""
    url = f"{os.environ['BRAIN_URL'].rstrip('/')}/api/live/{match_id}/beats"
    body = json.dumps({"momentIds": moment_ids}).encode()
    headers = {"Content-Type": "application/json", "x-live-key": os.environ.get("MATCHMIND_LIVE_KEY", "")}
    last: Exception | None = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers, method="POST"), timeout=90) as r:  # noqa: S310 - the Brain's https address
                return json.loads(r.read())
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            logging.warning("dispatch %s attempt %d failed: %s", match_id, i + 1, e)
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"the Brain did not answer for {match_id}") from last


@app.function_name("dispatch")
@app.cosmos_db_trigger(
    arg_name="docs", database_name="matchmind", container_name="moments", connection="COSMOS",
    lease_container_name="leases", lease_container_prefix="dispatch-", create_lease_container_if_not_exists=False,
    feed_poll_delay=500, max_items_per_invocation=50,
)
def dispatch_moments(docs: func.DocumentList) -> None:
    by_match: dict[str, list[str]] = {}
    for d in docs:
        by_match.setdefault(d["matchId"], []).append(d["id"])
    for match_id, ids in by_match.items():
        t0 = time.monotonic()
        out = _post_beats(match_id, ids)
        logging.info("dispatch %s: %d moments -> %s overlays, %s model calls, %.1f s", match_id, len(ids), out.get("overlaysWritten"), out.get("modelCalls"), time.monotonic() - t0)

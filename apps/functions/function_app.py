"""The event-driven part of the live pipeline: Functions on three kinds of trigger.

    simulator job ──▶ Blob `frames` (tracking chunks) ──(Event Grid)──▶ analyze ──▶ Cosmos `events` (physical facts, watermark)
    simulator job ──▶ Cosmos `events` (feed) ───────────(change feed)─▶ interpret ──▶ Cosmos `moments`, `overlays`
    Cosmos `moments` ──(change feed)──▶ dispatch ──▶ Brain ──▶ Cosmos `overlays`

* ``analyze``    an Event Grid trigger on blobs created in the `frames` container. Event Grid delivers at least once and in any order, so the Function does
                 not process "the chunk in the event": it drains the next chunks in order, under a lock (``live/analysis.py``).
* ``interpret``  reads only what is new, up to the lower of the feed's and the analyzer's watermark, and stores the moments it finds and the overlays
                 that need no model. Its state lives in memory while the instance is warm and in a signed checkpoint blob otherwise.
* ``dispatch``   asks the Brain to write the narrative overlays for new moments (the fast path: Editor, one model call per viewer cohort, Verifier).
* ``negotiate``  the SignalR handshake: a browser asks for a connection to the live hub (Azure SignalR Service, serverless mode, Microsoft Entra
                 authentication: no keys) and is handed the service's address and a short-lived token.
* ``push_*``     three more change-feed triggers (on `overlays`, `moments` and `events`) that **push** what was just stored to every connected browser
                 through the SignalR output binding, in batches (one message per match per invocation), so the page learns about an overlay the moment it is
                 written instead of at its next poll. The page still reads the Brain's feed once to catch up and now and then to reconcile.
* ``sweep``      a timer, every 30 seconds, that runs the first two for every live match: a safety net for a lost Event Grid event or a restarted instance.

All of it is idempotent, so the at-least-once delivery of a change feed or an Event Grid subscription (and a Brain that was asleep for the first attempt)
cannot duplicate anything. The Functions use the identity the app runs as for Cosmos DB and Blob Storage (no keys): ``COSMOS__accountEndpoint`` /
``COSMOS__credential`` / ``COSMOS__clientId`` configure the triggers, ``COSMOS_ENDPOINT``, ``STORAGE_ACCOUNT`` and ``AZURE_CLIENT_ID`` the stores.
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

from matchmind.live.analysis import AnalyzerWorker  # noqa: E402
from matchmind.live.blobs import AzureBlobs  # noqa: E402
from matchmind.live.pipeline import InterpretWorker  # noqa: E402
from matchmind.live.store import CosmosLiveStore  # noqa: E402

app = func.FunctionApp()
_workers: tuple[CosmosLiveStore, AnalyzerWorker, InterpretWorker] | None = None


def workers() -> tuple[CosmosLiveStore, AnalyzerWorker, InterpretWorker]:
    """Built once per instance and kept: the workers hold the analyzer's and the interpreter's state while the instance is warm."""
    global _workers
    if _workers is None:
        from azure.identity import ManagedIdentityCredential

        cred = ManagedIdentityCredential(client_id=os.environ.get("AZURE_CLIENT_ID"))
        store = CosmosLiveStore(os.environ["COSMOS_ENDPOINT"], credential=cred)
        account = os.environ["STORAGE_ACCOUNT"]
        frames, checkpoints = AzureBlobs(account, "frames", cred), AzureBlobs(account, "checkpoints", cred)
        _workers = (store, AnalyzerWorker(store, frames, checkpoints), InterpretWorker(store, checkpoints))
    return _workers


def _interpret(match_id: str) -> None:
    t0 = time.monotonic()
    out = workers()[2].run(match_id)
    if out.get("busy"):
        return
    logging.info(
        "interpret %s: read %s documents up to %s ms (feed %s, physical %s), %s moments (%s new), %s new overlays, finished=%s, %.2f s",
        match_id, out.get("read"), out.get("limitMs"), out.get("feedMs"), out.get("physicalMs"), out.get("moments"), len(out.get("newMoments", [])),
        out.get("newOverlays"), out.get("finished"), time.monotonic() - t0,
    )


def _analyze(match_id: str) -> None:
    t0 = time.monotonic()
    out = workers()[1].drain(match_id)
    if out.get("processed") or out.get("final"):
        logging.info("analyze %s: %s chunks, next %s, watermark %s ms, final=%s, %.2f s", match_id, out.get("processed"), out.get("next"), out.get("watermarkMs"), out.get("final"), time.monotonic() - t0)


@app.function_name("interpret")
@app.cosmos_db_trigger(
    arg_name="docs", database_name="matchmind", container_name="events", connection="COSMOS",
    lease_container_name="leases", lease_container_prefix="interpret-", create_lease_container_if_not_exists=False,
    feed_poll_delay=500, max_items_per_invocation=500,
)
def interpret_events(docs: func.DocumentList) -> None:
    for match_id in sorted({d["matchId"] for d in docs}):
        _interpret(match_id)


@app.function_name("analyze")
@app.event_grid_trigger(arg_name="event")
def analyze_chunk(event: func.EventGridEvent) -> None:
    """A tracking chunk was created: ``/blobServices/default/containers/frames/blobs/<match>/<index>.json.gz``."""
    subject = event.subject or ""
    if "/blobs/" not in subject:
        return
    name = subject.split("/blobs/", 1)[1]
    if "/" in name:
        _analyze(name.rsplit("/", 1)[0])


@app.function_name("sweep")
@app.timer_trigger(schedule="*/30 * * * * *", arg_name="timer", run_on_startup=False)
def sweep(timer: func.TimerRequest) -> None:
    """Every 30 seconds: for each live match, do what the triggers would have done (drain the chunks, interpret)."""
    store = workers()[0]
    for m in store.list_matches():
        if m.get("status") == "live" and m.get("physical") == "chunks":
            _analyze(m["matchId"])
            _interpret(m["matchId"])


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


# ----- SignalR: negotiate and push -------------------------------------------------------------------------------------------------------

HUB = "live"
SIGNALR = "AzureSignalRConnectionString"  # app settings AzureSignalRConnectionString__serviceUri / __credential / __clientId: the identity, no key
SHOWN_EVENTS = {"goal", "shot", "card", "substitution", "formation_change"}  # what the live page lists (live/api.py)
BATCH = 40  # documents per SignalR message (a message may not exceed 1 MB)


@app.function_name("negotiate")
@app.route(route="negotiate", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
@app.generic_input_binding(arg_name="connectionInfo", type="signalRConnectionInfo", hubName=HUB, connectionStringSetting=SIGNALR)
def negotiate(req: func.HttpRequest, connectionInfo) -> func.HttpResponse:  # noqa: ANN001
    return func.HttpResponse(connectionInfo, mimetype="application/json")


def _messages(docs: func.DocumentList, target: str, pick) -> str:  # noqa: ANN001
    """One SignalR message per match and batch: ``{"target": ..., "arguments": [{"matchId": ..., "items": [...]}]}`` as a JSON array."""
    by_match: dict[str, list[dict]] = {}
    for d in docs:
        item = pick(d)
        if item is not None:
            by_match.setdefault(d["matchId"], []).append(item)
    out = []
    for match_id, items in by_match.items():
        for i in range(0, len(items), BATCH):
            out.append({"target": target, "arguments": [{"matchId": match_id, "items": items[i : i + BATCH]}]})
    return json.dumps(out)


@app.function_name("push_overlays")
@app.cosmos_db_trigger(
    arg_name="docs", database_name="matchmind", container_name="overlays", connection="COSMOS",
    lease_container_name="leases", lease_container_prefix="push-overlays-", create_lease_container_if_not_exists=False,
    feed_poll_delay=500, max_items_per_invocation=100,
)
@app.generic_output_binding(arg_name="signalr", type="signalR", hubName=HUB, connectionStringSetting=SIGNALR)
def push_overlays(docs: func.DocumentList, signalr: func.Out[str]) -> None:
    signalr.set(_messages(docs, "overlays", lambda d: {**d["overlay"], "emittedMs": d["emittedMs"]}))


@app.function_name("push_moments")
@app.cosmos_db_trigger(
    arg_name="docs", database_name="matchmind", container_name="moments", connection="COSMOS",
    lease_container_name="leases", lease_container_prefix="push-moments-", create_lease_container_if_not_exists=False,
    feed_poll_delay=500, max_items_per_invocation=50,
)
@app.generic_output_binding(arg_name="signalr", type="signalR", hubName=HUB, connectionStringSetting=SIGNALR)
def push_moments(docs: func.DocumentList, signalr: func.Out[str]) -> None:
    keys = ("id", "type", "label", "salience", "detectedAt", "subjectTeam", "facts")
    signalr.set(_messages(docs, "moments", lambda d: {**{k: d["moment"].get(k) for k in keys}, "createdMs": d.get("createdMs")}))


@app.function_name("push_events")
@app.cosmos_db_trigger(
    arg_name="docs", database_name="matchmind", container_name="events", connection="COSMOS",
    lease_container_name="leases", lease_container_prefix="push-events-", create_lease_container_if_not_exists=False,
    feed_poll_delay=500, max_items_per_invocation=500,
)
@app.generic_output_binding(arg_name="signalr", type="signalR", hubName=HUB, connectionStringSetting=SIGNALR)
def push_events(docs: func.DocumentList, signalr: func.Out[str]) -> None:
    keys = ("id", "type", "clock", "team", "player", "receiver", "outcome", "location")

    def pick(d):  # noqa: ANN001, ANN202
        if d.get("kind") != "feed" or d["doc"].get("type") not in SHOWN_EVENTS:
            return None
        return {"n": d["n"], "arrivalMs": d["arrivalMs"], **{k: d["doc"].get(k) for k in keys}}

    msgs = _messages(docs, "events", pick)
    if msgs != "[]":
        signalr.set(msgs)

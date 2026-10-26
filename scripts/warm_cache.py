"""Warm the shared story cache: play every demo match through a deployed Brain for every viewer type, so the first real viewer gets instant, verified text.

    python scripts/warm_cache.py <brain url> [parallel sessions, default 3]

For each demo (data/demos.json) it writes the stories for 18 viewer types: analyst and casual, English, Spanish and Turkish, with a neutral, a home-club and an away-club
perspective. A session writes for at most 4 viewer types, so that is 5 sessions per demo, played at 10x. The cache entries do not expire (the key carries the model and the prompt version, so a new prompt or model starts a fresh set: run it again then).
The sessions run in a few at a time so that the model deployment's tokens-a-minute limit is not hit: a story the model misses is a template, and a template is not cached.
"""
import itertools
import json
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

B = sys.argv[1].rstrip("/")
PARALLEL = int(sys.argv[2]) if len(sys.argv) > 2 else 3
DEMOS = json.loads((Path(__file__).resolve().parent.parent / "data" / "demos.json").read_text())
lock = threading.Lock()
last_start = [0.0]


def call(method, path, body=None, timeout=60):
    req = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None, headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"{}")


def cohorts_for(demo):
    out = []
    for perspective in ("neutral", demo["home"], demo["away"]):
        for language in ("en", "es", "tr"):
            for mode in ("analyst", "casual"):
                out.append({"mode": mode, "language": language, "perspective": perspective})
    return [out[i:i + 4] for i in range(0, len(out), 4)]


def run(job):
    demo, group = job
    name = f"{demo['id']} {','.join(c['mode'][0] + c['language'] + c['perspective'][:1] for c in group)}"
    with lock:  # the start limit is 6 a minute: space the starts out
        wait = last_start[0] + 11 - time.time()
        if wait > 0:
            time.sleep(wait)
        last_start[0] = time.time()
    try:
        sid = call("POST", "/api/stream", {"demo": demo["id"], "speed": 10, "fromMinute": 0, "cohorts": group[:2]}, timeout=120)["streamId"]
        for c in group[2:]:
            call("POST", f"/api/stream/{sid}/cohorts", c)
    except Exception as e:  # noqa: BLE001
        print(f"FAILED to start {name}: {e}", flush=True)
        return 0
    print(f"started  {name} -> {sid}", flush=True)
    t0 = time.time()
    status = "?"
    while time.time() - t0 < 20 * 60:
        time.sleep(12)
        try:
            p = call("GET", f"/api/stream/{sid}/feed?event=999999&since=999999")
            status = p.get("status", "?")
            if status == "finished":
                break
        except Exception as e:  # noqa: BLE001
            print(f"  poll error {name}: {e}", flush=True)
    try:
        call("DELETE", f"/api/stream/{sid}")
    except Exception:  # noqa: BLE001
        pass
    print(f"finished {name} ({status}, {time.time() - t0:.0f} s)", flush=True)
    return 1


def main():
    jobs = list(itertools.chain.from_iterable([(d, g) for g in cohorts_for(d)] for d in DEMOS))
    print(f"{len(jobs)} sessions, {PARALLEL} at a time", flush=True)
    before = call("GET", "/api/ops")
    with ThreadPoolExecutor(PARALLEL) as pool:
        done = sum(pool.map(run, jobs))
    after = call("GET", "/api/ops")
    print(f"done: {done}/{len(jobs)} sessions; cache entries {before['cache']['entries']} -> {after['cache']['entries']}; stories {after['narrative']}", flush=True)


if __name__ == "__main__":
    main()

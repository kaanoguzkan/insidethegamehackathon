"""Load test of the live matches: N viewers at one speed, each polling the feed every 0.7 s, against a deployed Brain.

    python scripts/load_test.py <brain url> <viewers> <speed 1|5|10> <seconds> [seconds between starts]

The public start limit is 6 a minute per client, so more than 6 viewers need a gap (11 s) between starts. Prints the feed poll latency, the errors and the stories each viewer got.
"""
import json
import statistics
import sys
import threading
import time
import urllib.request

B = sys.argv[1].rstrip("/")
N = int(sys.argv[2])
SPEED = int(sys.argv[3])
SECS = int(sys.argv[4])
def call(m,p,b=None,t=60):
    r=urllib.request.Request(B+p,method=m,data=json.dumps(b).encode() if b is not None else None,headers={"content-type":"application/json"})
    return json.loads(urllib.request.urlopen(r,timeout=t).read())
for i in range(30):
    try: call("GET","/health"); break
    except Exception: time.sleep(5)
demos=["red-card-drama","pressing-collapse","eight-goal-thriller"]
lat=[]; errs=[0]; stories={}; clocks={}
stop=threading.Event()
def viewer(k):
    demo=demos[k%3]
    t0=time.time()
    try: sid=call("POST","/api/stream",{"demo":demo,"speed":SPEED,"fromMinute":0,"cohorts":[{"mode":"casual" if k%2 else "analyst","language":"en"}]},t=120)["streamId"]
    except Exception as e: errs[0]+=1; print("start failed",e); return
    start=time.time()-t0
    cur={"event":-1,"since":0,"msince":0,"snap":0,"av":0,"rv":0}; seen=set(); first=None
    while not stop.is_set():
        t=time.time()
        try:
            q="&".join(f"{a}={b}" for a,b in cur.items()); p=call("GET",f"/api/stream/{sid}/feed?full=1&{q}",t=30)
            lat.append(time.time()-t)
            cur={"event":p["eventCursor"],"since":p["overlayCursor"],"msince":p["momentCursor"],"snap":p["snapshotCursor"],"av":p["analyticsVersion"],"rv":p["recapCursor"]}
            for o in p["overlays"]:
                if o["kind"]=="lower_third": seen.add(o["id"])
            clocks[k]=p["clockMs"]/60000
        except Exception: errs[0]+=1
        time.sleep(0.7)
    stories[k]=(len(seen), round(start,1), demo)
    try: call("DELETE",f"/api/stream/{sid}")
    except Exception: pass
ts=[threading.Thread(target=viewer,args=(k,),daemon=True) for k in range(N)]
for t in ts: t.start(); time.sleep(float(sys.argv[5]) if len(sys.argv) > 5 else 1.0)
time.sleep(SECS); stop.set()
for t in ts: t.join(timeout=20)
lat.sort()
print(f"{N} viewers at {SPEED}x for {SECS}s: feed polls {len(lat)}, errors {errs[0]}, median {statistics.median(lat)*1000:.0f} ms, p95 {lat[int(len(lat)*0.95)]*1000:.0f} ms, max {lat[-1]*1000:.0f} ms")
print("clock minutes per viewer", {k:round(v,1) for k,v in sorted(clocks.items())})
print("stories per viewer (count, start s, demo)", dict(sorted(stories.items())))
ops=call("GET","/api/ops"); print("ops", ops["streams"], "p95", ops["requests"]["p95Ms"], "errors", ops["requests"]["errors"])

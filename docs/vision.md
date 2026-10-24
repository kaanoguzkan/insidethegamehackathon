# Auto-eventing from video

The challenge asks for "a model over an incoming video feed to generate the pass and speed metrics automatically, rather than tagging them by hand". No footage is
provided, so MatchMind makes its own feed and reads it the way a studio would meet one: video in, metrics out. A live match runs this stage for real.

```mermaid
flowchart LR
  SIM["Simulator<br/>(the provider's truth)"] -->|"tracking chunks"| VF["Video feed<br/>render frames, 4 px a metre"]
  VF -->|"pixels only"| DET["Detector<br/>colour blobs, centroids,<br/>ball size gives height"]
  DET --> TRK["Tracker<br/>one track per player slot"]
  EV["Event feed<br/>(who did what, where)"] -->|"identity anchors"| TRK
  TRK -->|"reconstructed chunks"| AN["Physical analyzer"]
  AN -->|"speeds, sprints, pass difficulty, shot speed"| INT["Interpreter, agents, overlays"]
```

## What each part does (`src/matchmind/vision/`)

* **Render** (`render.py`). A top-down frame from tracking: pitch, lines, players in team colours (anti-aliased discs about a metre wide), the ball (drawn bigger
  the higher it is, as a camera sees it), camera noise and a little colour drift. Pixel and pitch coordinates are a plain scaling, so the pitch lines are there for a
  homography if the camera were not top-down. This is the stand-in for the video provider; nothing downstream sees the simulator's numbers.
* **Detect** (`detect.py`). Per frame, from the pixels alone: a colour mask per team and for the ball, connected blobs, a centroid per blob. A blob with
  about two players' worth of pixels is split with k-means. The ball's apparent size gives its height. 
* **Track** (`track.py`). One track per player slot. Detections of a team are matched to its tracks with the Hungarian algorithm (gated by what a player can run in
  a frame) and a *role prior* (where a player usually stands relative to his team) to break ties when two cross. A track that is not seen is carried on its velocity
  for a second and then let go (a sending-off is simply a track that does not come back); a detection nobody claims is given to a lost track. The tracker starts from
  the line-up at kick-off, as a production tracker starts from a team sheet. When the **event feed** says who did something and where, and another track is
  there, the two tracks swap identities: events anchor *who is who*.
* **Feed** (`feed.py`). One per live match. Chunks published by the match player are rendered, detected, tracked and re-published as tracking chunks in the video
  feed's own store; the physical analyzer reads that store. A viewer who joins mid-match gets the earlier chunks from the provider's archive and the video model from
  the join point.
* **Preview** (`GET /api/stream/{id}/vision/frame?atMs=`, the *Video feed* card on a live match). The frame at the viewer's position with every detection boxed,
  and the running error figures.

## How good it is

Measured against the simulator's truth (`matchmind vision-eval <demo>`), whole matches of 5 Hz tracking:

| Match | Player position error (RMS) | Ball position error (RMS) | Player speed error | Ball speed error | Ball seen | Players kept as themselves |
|---|---|---|---|---|---|---|
| red-card-drama | 8.3 cm | 3.6 cm | 1.5 km/h | 0.45 km/h | 100% | 75% |
| pressing-collapse | 8.8 cm | 3.6 cm | 1.6 km/h | 0.46 km/h | 100% | 76% |
| eight-goal-thriller | 9.5 cm | 3.5 cm | 2.2 km/h | 0.43 km/h | 100% | 64% |

* **Position and speed are what the metrics need and they are close**: a few centimetres, about a kilometre an hour.
* **Who is who is the weak spot**, and it is honest to say so. Two simulated players can stand 0.1 to 0.4 m apart, which from above is one blob; when they separate
  the tracker can swap them. The event feed (a pass, a shot, a tackle names the player and the place) corrects most swaps; the rest is shown as the last column. The facts that
  name a player (a sprint, the fastest runner) can therefore be wrong about *which* player; facts about the ball, the team and the moment are not affected.
* **One reading for everyone.** A demo match is deterministic, so what the video model sees in it is the same for every viewer. It is read **once per demo**
  (`vision/shared.py`), not once per viewer: a background worker reads each demo chunk by chunk, and a session takes the rebuilt chunk as it is ready (or the provider's
  tracking for a chunk the worker has not reached, so a match never waits). The reading can also be **baked** ahead of time (`matchmind vision-bake <demo>` writes
  `data/vision/<demo>.mmv` (a plain container: a JSON header and the chunks, no pickle), which the Docker image carries), so a freshly started Brain has nothing left to compute. Before this, every viewer paid for their own
  reading, which was the main reason several viewers made the Brain lag.
* **Cost.** About 3 to 5 ms a frame on a laptop (the background is subtracted first, so only the few hundred pixels that differ from the empty pitch are classified), so a
  5-second chunk takes roughly 0.1 s of one core; on the Container App's cores it is slower (about 0.4 s a chunk before this was optimised). It runs in its own thread,
  in order, and the analyzer simply waits for the next chunk. The first version of the tracker lost 40 cm on average over a whole match because everyone moves at
  half-time; it now restarts a team from its pattern of roles when most of its tracks lose their detection at once.

## What this is not

* It is a *synthetic* video feed made from tracking, with a deliberately simple look (top-down, flat colours), not broadcast footage; a production system would
  need a detector trained on real frames and a camera model. The stages and the interface (video in, tracking chunks out) are the ones that would stay.
* The ball's height is estimated from its apparent size, which is a crude stand-in for a real height measurement.
* "Ball in play" is taken from the event feed, not from the video.
* The tracker is told the line-up and the starting positions when a match (or a viewer's join point) begins.

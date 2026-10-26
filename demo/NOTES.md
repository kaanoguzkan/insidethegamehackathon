# Demo video

Two videos: a **2-minute demo** (the one in the form's Demo video field) and an optional **5-minute walkthrough** (linked from the README). English captions burned in and an English voice-over made with Azure AI Speech (neural HD voice en-US-Andrew); no logos or music.
Record against the deployed site; wait about 2 minutes after a deploy so the demos preload. `demo/pages/figure.html` shows an architecture figure full screen with its animation on
(serve the repo root over http; `?still=1` for a still).

## What the rules ask (OFFICIAL RULES 4.4, 4.9, 6.2)

* Under 2 minutes (judges need not watch beyond 2:00); it shows the project running; public URL on YouTube, Vimeo, Facebook Video or Youku; no third-party trademarks or copyrighted music; English or English captions.

## Shot list, 2 minutes

| Time | Shows | Caption idea |
|---|---|---|
| 0:00 | Start page | "Rifinitore: football, explained as it happens." |
| 0:10 | Live: kick-off, a goal, a story with its evidence | "Every sentence is written for this minute, and checked." |
| 0:30 | Video feed card: detections boxed | "No tracking given: a model reads the video." |
| 0:42 | Speed 1 → 10, changed while it plays | "Your own clock, any speed." |
| 0:55 | Ask in the live match | "Ask the match. It never uses what has not happened yet." |
| 1:10 | Two viewers: analyst in English, fan in Spanish | "Same moment, two fans, two stories." |
| 1:25 | Story figure (animated) | "Code computes, agents explain, a verifier checks." |
| 1:37 | Cloud pipeline, then Operations (about 15 s together) | "Event Grid, Functions, SignalR. Latency and errors in view." |
| 1:52 | End card | "Rifinitore: football, explained as it happens, and checked." |

Upload as Public and check that it plays when logged out, then put the URL in `SUBMISSION.md` and the README.

## Voice-over and subtitles (the recorded cut, 1:39)

The voice is Azure AI Speech (`en-US-Andrew:DragonHDLatestNeural`), one clip per phrase; "Rifinitore" is given an Italian pronunciation with an SSML phoneme. The subtitles are drawn from the same phrase list and timings, so voice, picture and text cannot drift apart; `rifinitore-demo.en.srt` is the same text for a YouTube caption upload.

* This is Rifinitore: football, explained as it happens.
* Start a live match.
* Every moment is found, explained and checked while the match is played.
* Every number links to its evidence,
* and with no tracking data given, a model reads the video feed itself.
* Change the speed while it plays.
* The match keeps its own clock for you.
* Ask the match anything.
* The answer comes only from what has already happened,
* and every number in it is checked against the data.
* Two viewers, one match:
* the same moment told in English and in Spanish, for different fans.
* Or replay a recorded match.
* Open the evidence behind a goal: the numbers, how the story was made and the events behind it.
* Then the tactics,
* and every number behind the match.
* Five stages: ingest, analyse, interpret, explain and personalise, each one running on Azure.
* Code computes the numbers. Agents write the story. A verifier stops any claim the data cannot support.
* It is built on Azure: Container Apps, Event Grid, Functions, Cosmos DB and SignalR, with Foundry agents and one managed identity, so there are no keys.
* The same match also runs as an event-driven cloud pipeline,
* and each moment becomes a verified story within seconds.
* Operations shows latency, errors and live capacity as they happen.
* Rifinitore. Football, explained as it happens, and checked.

"""Auto-eventing from video: a frame is rendered from tracking, the detector reads only its pixels, the tracker gives back tracking chunks."""

from __future__ import annotations

import time

import numpy as np
import pytest

from matchmind.live import session as S
from matchmind.live.pipeline import Intel
from matchmind.tracking.frames import iter_chunks
from matchmind.vision.detect import detect
from matchmind.vision.feed import events_for_anchoring
from matchmind.vision.render import png, render_frame, to_m, to_px
from matchmind.vision.track import VideoTracker


def test_pixels_and_pitch_coordinates_are_inverse():
    x, y = to_px(37.5, 12.25)
    assert np.allclose(to_m(x, y), (37.5, 12.25))


def test_the_detector_finds_every_player_and_the_ball_from_pixels_alone(match):
    ch = list(iter_chunks(match))[10]
    f, b = ch.frames[3], ch.ball[3]
    det = detect(render_frame(f, b, np.random.default_rng(1)))
    assert abs(len(det.home) - 11) <= 1 and abs(len(det.away) - 11) <= 1  # two players standing on each other make one blob, as in real video
    for found, truth in ((det.home, f[:11]), (det.away, f[11:])):
        assert np.linalg.norm(found[:, None, :] - truth[None], axis=2).min(axis=1).max() < 0.3  # every blob within 30 cm of a player
    assert det.ball is not None and np.hypot(*(det.ball[:2] - b[:2])) < 0.3


def test_a_tracked_stretch_of_the_match_is_close_to_the_truth(match):
    chunks = list(iter_chunks(match))[:40]
    vt = VideoTracker(chunks[0].frames[0])
    ev = events_for_anchoring([], 5)
    for ch in chunks:
        out = vt.process(ch, ev)
        assert out.frames.shape == ch.frames.shape and out.slots == ch.slots and out.first_frame == ch.first_frame
    s = vt.stats.summary()
    assert s["positionRmseCm"] < 25 and s["ballRmseCm"] < 25 and s["ballSeen"] > 0.95
    assert s["speedErrorKmh"] < 3.0


def test_a_player_the_video_no_longer_shows_is_let_go(match):
    ch = list(iter_chunks(match))[3]
    vt = VideoTracker(ch.frames[0])
    gone = ch.frames.copy()
    gone[:, 4] = np.nan  # a sending-off: slot 4 is no longer on the pitch
    out = vt.process(type(ch)(**{**ch.__dict__, "frames": gone}))
    assert np.isnan(out.frames[-1, 4, 0]) and not np.isnan(out.frames[-1, 5, 0])


def test_the_png_is_a_picture():
    img = render_frame(np.full((22, 2), np.nan), np.array([50.0, 30.0, 0.0]))
    data = png(img)
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 100


@pytest.fixture(scope="module")
def vision_hub():
    h = S.StreamHub(intel=Intel.load(), tick_s=0.02, max_sessions=2, vision=True)
    h.speeds = (*S.SPEEDS, 2000.0)
    h.preload(["red-card-drama"])
    return h


def test_a_live_match_reads_its_physical_facts_from_the_video_feed(vision_hub):
    s = vision_hub.start("red-card-drama", speed=2000.0, from_minute=88.0)
    assert s.vision is not None
    t0 = time.monotonic()
    while time.monotonic() - t0 < 120 and not (s.finished_at is not None):
        time.sleep(0.1)
    assert s.finished_at is not None and s.error is None
    st = s.vision.stats()
    assert st["chunks"] > 5 and st["positionRmseCm"] < 25, st  # the late chunks went through the video model; the earlier ones are the archive
    kinds = {d["kind"] for d in vision_hub.store.docs(s.id)}
    assert "physical" in kinds or "enrichment" in kinds  # facts the analyzer derived from the reconstruction
    assert s.vision.frame_png(s.vision.tracker.stats.frames and max(s.vision._det)) is not None

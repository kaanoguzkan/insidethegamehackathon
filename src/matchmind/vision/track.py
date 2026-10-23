"""From detections back to tracking chunks.

The tracker keeps one track per player slot. Each frame it matches the detections of a team to that team's tracks (nearest, one to one, with a gate of what
a player can run in a frame), carries a track along on its last velocity when it is not seen for a moment, and lets go of a track that has been missing for
a second (a player sent off or substituted). It starts from the line-up at kick-off, as a production tracker starts from a team sheet; everything after that
comes from the pixels. The chunk it returns is exactly the format the physical analyzer reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from ..tracking.frames import Chunk
from .detect import Detections, detect
from .render import render_frame

GATE_M = 4.0  # farthest a detection can be from a track's prediction and still be that player (a sprint is ~2 m in a frame)
LOST_AFTER = 5  # frames a track is carried before it is let go
ROLE_WEIGHT = 0.6  # how much the role prior counts against distance in matching
ROLE_RATE = 0.02
ANCHOR_M = 3.0  # an event's player is the track within this far of the event's location
REACQUIRE_M = 30.0  # how far from where it was last seen a lost track can be picked up again
DT = 0.2


@dataclass
class Track:
    pos: np.ndarray
    vel: np.ndarray = field(default_factory=lambda: np.zeros(2))
    missing: int = 0
    on: bool = True
    role: np.ndarray | None = None  # running average of where this player stands relative to his team's centre: who he is, when two players cross


@dataclass
class VisionStats:
    frames: int = 0
    pos_sq_cm: float = 0.0  # summed squared position error, centimetres
    pos_n: int = 0
    id_kept: int = 0
    id_n: int = 0
    ball_sq_cm: float = 0.0
    ball_n: int = 0
    ball_seen: int = 0
    ball_frames: int = 0
    swaps_fixed: int = 0
    spd_abs: float = 0.0  # summed |speed error|, km/h, over players seen in two frames in a row
    spd_n: int = 0
    ball_spd_abs: float = 0.0
    ball_spd_n: int = 0

    def summary(self) -> dict:
        return {
            "frames": self.frames,
            "positionRmseCm": round(float(np.sqrt(self.pos_sq_cm / self.pos_n)), 1) if self.pos_n else None,
            "identityKept": round(self.id_kept / self.id_n, 4) if self.id_n else None,
            "ballRmseCm": round(float(np.sqrt(self.ball_sq_cm / self.ball_n)), 1) if self.ball_n else None,
            "speedErrorKmh": round(self.spd_abs / self.spd_n, 2) if self.spd_n else None,
            "ballSpeedErrorKmh": round(self.ball_spd_abs / self.ball_spd_n, 2) if self.ball_spd_n else None,
            "ballSeen": round(self.ball_seen / self.ball_frames, 4) if self.ball_frames else None,
            "identityFixedByEvents": self.swaps_fixed,
        }


class VideoTracker:
    """Turns the frames of a video feed into tracking chunks, one chunk after another (the tracker's state carries over)."""

    def __init__(self, first_frame: np.ndarray, seed: int = 0) -> None:
        self.tracks = [Track(pos=first_frame[i].astype(np.float64), on=not np.isnan(first_frame[i, 0])) for i in range(22)]
        self.rng = np.random.default_rng(seed)
        self.stats = VisionStats()
        self.last_ball = np.array([52.5, 34.0, 0.0])
        self.last_detections: dict[int, Detections] = {}  # by frame index, for the preview
        self._prev: tuple | None = None

    def _step_team(self, slots: range, dets: np.ndarray) -> None:
        tr = [self.tracks[i] for i in slots]
        active = [j for j, t in enumerate(tr) if t.on]
        claimed: set[int] = set()  # detections that went to a track
        matched: set[int] = set()  # tracks (indices into ``tr``) that got a detection this frame
        centre = np.mean([tr[j].pos for j in active], axis=0) if active else np.zeros(2)
        if active and len(dets):
            pred = np.array([tr[j].pos + tr[j].vel * DT for j in active])
            cost = np.linalg.norm(pred[:, None, :] - dets[None, :, :], axis=2)
            dc = dets.mean(axis=0)
            role = np.array([tr[j].role if tr[j].role is not None else tr[j].pos - centre for j in active])
            prior = np.linalg.norm(role[:, None, :] - (dets - dc)[None, :, :], axis=2)
            rows, cols = linear_sum_assignment(np.where(cost > GATE_M, 1e3, cost + ROLE_WEIGHT * prior))
            for r, c in zip(rows, cols, strict=True):
                if cost[r, c] > GATE_M:
                    continue
                t = tr[active[r]]
                t.vel = 0.5 * t.vel + 0.5 * (dets[c] - t.pos) / DT  # a little smoothing: a detection is a pixel-sized estimate
                t.pos, t.missing = dets[c].copy(), 0
                off = dets[c] - dc
                t.role = off if t.role is None else (1 - ROLE_RATE) * t.role + ROLE_RATE * off
                claimed.add(c)
                matched.add(active[r])
        for j in active:
            if j in matched:
                continue
            t = tr[j]
            t.missing += 1
            t.pos = t.pos + t.vel * DT
            if t.missing > LOST_AFTER:
                t.on = False
        # A detection nobody claimed is a track that was lost (a player hidden in a cluster, a restart that moved everyone): the nearest lost track takes it
        free = [c for c in range(len(dets)) if c not in claimed]
        lost = [j for j, t in enumerate(tr) if (not t.on) or t.missing > 0]
        if free and lost:
            cost = np.linalg.norm(np.array([tr[j].pos for j in lost])[:, None, :] - dets[free][None, :, :], axis=2)
            rows, cols = linear_sum_assignment(cost)
            for r, c in zip(rows, cols, strict=True):
                if cost[r, c] > REACQUIRE_M:
                    continue
                t = tr[lost[r]]
                t.pos, t.vel, t.missing, t.on = dets[free[c]].copy(), np.zeros(2), 0, True

    def _anchor(self, slot_of: dict[str, int], events: list[tuple[int, str, float, float]], frame: int) -> None:
        """The event feed names who did what and where: if the track at that place belongs to another slot, the two tracks swap identities."""
        for f, player, x, y in events:
            if f != frame or player not in slot_of:
                continue
            s = slot_of[player]
            lo, hi = (0, 11) if s < 11 else (11, 22)
            near = [(np.hypot(*(self.tracks[j].pos - (x, y))), j) for j in range(lo, hi) if self.tracks[j].on]
            if not near:
                continue
            d, j = min(near)
            if j != s and d < ANCHOR_M and self.tracks[s].on and np.hypot(*(self.tracks[s].pos - (x, y))) > d:
                self.tracks[s], self.tracks[j] = self.tracks[j], self.tracks[s]
                self.stats.swaps_fixed += 1

    def process(self, chunk: Chunk, events: list[tuple[int, str, float, float]] | None = None, keep_frames: bool = False) -> Chunk:
        """The chunk as the video model saw it. ``chunk`` is the truth the video is rendered from; only the rendered pixels reach the detector."""
        n = chunk.n
        events = events or []
        slot_of = {p: i for i, p in enumerate(chunk.slots)}
        out = np.full((n, 22, 2), np.nan, dtype=np.float32)
        ball = np.zeros((n, 3), dtype=np.float32)
        for i in range(n):
            img = render_frame(chunk.frames[i], chunk.ball[i], self.rng)
            det = detect(img)
            if keep_frames:
                self.last_detections[chunk.first_frame + i] = det
            self._step_team(range(0, 11), det.home)
            self._step_team(range(11, 22), det.away)
            self._anchor(slot_of, events, chunk.first_frame + i)
            for s, t in enumerate(self.tracks):
                if t.on:
                    out[i, s] = t.pos
            if det.ball is not None:
                self.last_ball = det.ball
                self.stats.ball_seen += 1
            ball[i] = self.last_ball
            self.stats.ball_frames += 1
            self._score(chunk.frames[i], out[i], chunk.ball[i], ball[i])
            self.stats.frames += 1
        return Chunk(match_id=chunk.match_id, index=chunk.index, start_ms=chunk.start_ms, hz=chunk.hz, slots=chunk.slots, frames=out, ball=ball, alive=chunk.alive)

    def _score(self, truth: np.ndarray, seen: np.ndarray, truth_ball: np.ndarray, seen_ball: np.ndarray) -> None:
        """Score one frame. Position error does not depend on identity (each tracked player against the nearest true player of the same team): who is
        who is scored apart, as ``identityKept``."""
        s = self.stats
        for lo, hi in ((0, 11), (11, 22)):
            t, o = truth[lo:hi], seen[lo:hi]
            t, o = t[~np.isnan(t[:, 0])], o[~np.isnan(o[:, 0])]
            if len(t) and len(o):
                d = np.linalg.norm(o[:, None, :] - t[None, :, :], axis=2).min(axis=1) * 100
                s.pos_sq_cm += float((d**2).sum())
                s.pos_n += len(o)
        both = ~np.isnan(truth[:, 0]) & ~np.isnan(seen[:, 0])
        if both.any():
            d = np.linalg.norm(seen[both][:, None, :] - truth[None, :, :], axis=2)
            d = np.where(np.isnan(d), 1e9, d)
            s.id_kept += int((np.argmin(d, axis=1) == np.flatnonzero(both)).sum())
            s.id_n += int(both.sum())
        if self._prev is not None:
            pt, po, pb_t, pb_o = self._prev
            ok = both & ~np.isnan(pt[:, 0]) & ~np.isnan(po[:, 0])
            if ok.any():
                v_t = np.linalg.norm(truth[ok] - pt[ok], axis=1) / DT * 3.6
                v_o = np.linalg.norm(seen[ok] - po[ok], axis=1) / DT * 3.6
                s.spd_abs += float(np.abs(v_t - v_o).sum())
                s.spd_n += int(ok.sum())
            vb_t = np.linalg.norm(truth_ball[:2] - pb_t[:2]) / DT * 3.6
            vb_o = np.linalg.norm(seen_ball[:2] - pb_o[:2]) / DT * 3.6
            if vb_t < 150:
                s.ball_spd_abs += float(abs(vb_t - vb_o))
                s.ball_spd_n += 1
        self._prev = (truth.copy(), seen.copy(), truth_ball.copy(), seen_ball.copy())
        if not np.isnan(truth_ball[0]):
            s.ball_sq_cm += float(np.sum((truth_ball[:2] - seen_ball[:2]) ** 2)) * 1e4
            s.ball_n += 1

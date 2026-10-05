"""Physical auto-eventing from tracking.

The analyzer reads only what a tracking provider would deliver (player and ball positions
in 5-second chunks) plus the event stream, and derives physical facts the event feed does
not contain:

* ``sprint`` / ``top_speed`` / ``distance_milestone`` events per player (speed and distance
  indicators for on-screen player tags, triggered when thresholds are reached)
* ``team_shape`` snapshots: defensive-line height, width and length every 30 s
* *enrichments* for passes and shots: ball speed, shot speed and the pressure / lane context
  needed to rate pass difficulty

It is incremental: feed events with :meth:`add_events` and chunks with
:meth:`process_chunk`; each call returns whatever became computable. That is how the
Azure Function runs it, one blob-created trigger per chunk. :func:`analyze_match` runs the
same code over a finished match.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..core import geometry as G
from ..core.clock import clock_from_ms
from .frames import Chunk, iter_chunks

SPRINT_KMH = 25.0
TOP_SPEED_KMH = 32.0
MIN_SPRINT_FRAMES = 5  # one second at 5 Hz
DISTANCE_MILESTONES_KM = (5.0, 8.0, 10.0)
SHAPE_WINDOW_CHUNKS = 6  # 30 seconds
LOOKAHEAD_FRAMES = 6  # frames after an event needed to measure ball speed
HISTORY_CHUNKS = 10


def pressure_at(point: np.ndarray, opp_positions: np.ndarray) -> float:
    """How closely a point is marked: 0 (free) to 1 (smothered)."""
    pts = opp_positions[~np.isnan(opp_positions[:, 0])]
    if len(pts) == 0:
        return 0.0
    d = np.hypot(pts[:, 0] - point[0], pts[:, 1] - point[1])
    return float(min(1.0, np.exp(-np.power(d / 2.8, 1.5)).sum()))


def lane_block(start: np.ndarray, end: np.ndarray, opp_positions: np.ndarray) -> float:
    """How much a passing lane is blocked by opponents: 0 (clear) to 1 (blocked)."""
    pts = opp_positions[~np.isnan(opp_positions[:, 0])]
    ab = end - start
    l2 = float(ab @ ab)
    if len(pts) == 0 or l2 < 1e-6:
        return 0.0
    tt = np.clip(((pts - start) @ ab) / l2, 0.0, 1.0)
    closest = start + tt[:, None] * ab
    dd = np.hypot(pts[:, 0] - closest[:, 0], pts[:, 1] - closest[:, 1])
    mask = (tt > 0.12) & (tt < 0.95)
    if not mask.any():
        return 0.0
    return float(max(0.0, 1.0 - dd[mask].min() / 2.6))


@dataclass
class AnalyzerOutput:
    events: list[dict] = field(default_factory=list)  # sprint, top_speed, distance_milestone, team_shape
    enrichments: list[dict] = field(default_factory=list)  # physics docs keyed to pass / shot events

    def extend(self, other: AnalyzerOutput) -> None:
        self.events.extend(other.events)
        self.enrichments.extend(other.enrichments)


class PhysicalAnalyzer:
    def __init__(self, meta: dict) -> None:
        self.match_id = meta["matchId"]
        self.hz = meta["hz"]
        self.dt = 1.0 / self.hz
        self.clubs = [meta["home"]["id"], meta["away"]["id"]]
        self.chunk_ticks = meta["chunkTicks"]

        self.attack_dirs: dict[int, dict[str, int]] = {}
        self.period_start_frame: dict[int, int] = {}
        self.p2_start_ms: int | None = None
        for p in meta.get("periods", []):  # known up front in batch mode; also learnt from events
            self._register_period(p["period"], p["startMs"], p["attackDirection"])

        self.chunks: dict[int, Chunk] = {}
        self.raw_speed: list[np.ndarray] = []  # per frame, (22,) m/s
        self.step_dist: list[np.ndarray] = []
        self.smoothed_upto = 0  # frames [0, smoothed_upto) have been analysed
        self.last_pos: np.ndarray | None = None
        self.n_frames = 0

        self.run_len: dict[str, int] = {}
        self.run_start: dict[str, int] = {}
        self.run_peak: dict[str, float] = {}
        self.run_peak_frame: dict[str, int] = {}
        self.cum_dist: dict[str, float] = {}
        self.milestones_hit: dict[str, int] = {}

        self.pending: list[dict] = []
        self.shape_acc: dict[int, list[tuple]] = {0: [], 1: []}
        self.x_counter = 0

    # ----- setup -----------------------------------------------------------------------------

    def _register_period(self, period: int, start_ms: int, directions: dict[str, int]) -> None:
        self.attack_dirs[period] = dict(directions)
        self.period_start_frame[period] = round(start_ms * self.hz / 1000)
        if period == 2:
            self.p2_start_ms = start_ms

    def add_events(self, events: list[dict]) -> None:
        for e in events:
            t = e["type"]
            if t == "period_start":
                p = e["attributes"].get("period", e["clock"]["period"])
                self._register_period(p, e["clock"]["matchMs"], e["attributes"]["attackDirection"])
            elif t in ("pass", "shot"):
                if not any(p["id"] == e["id"] for p in self.pending):
                    self.pending.append(e)

    # ----- chunk processing ---------------------------------------------------------------------

    def process_chunk(self, chunk: Chunk) -> AnalyzerOutput:
        out = AnalyzerOutput()
        self.chunks[chunk.index] = chunk
        for old in [i for i in self.chunks if i < chunk.index - HISTORY_CHUNKS]:
            del self.chunks[old]

        # Raw speed and step distance per frame.
        for k in range(chunk.n):
            pos = chunk.frames[k]
            f = chunk.first_frame + k
            if self.last_pos is None or f in self.period_start_frame.values():
                step = np.zeros(22)
            else:
                d = pos - self.last_pos
                step = np.hypot(d[:, 0], d[:, 1])
                step = np.where(np.isfinite(step), step, 0.0)
            self.raw_speed.append(step / self.dt)
            self.step_dist.append(step)
            self.last_pos = pos
        self.n_frames = chunk.first_frame + chunk.n

        out.extend(self._analyse_frames(upto=self.n_frames - 1))
        out.extend(self._enrich_pending())
        self._accumulate_shape(chunk)
        if chunk.index % SHAPE_WINDOW_CHUNKS == SHAPE_WINDOW_CHUNKS - 1:
            out.events.extend(self._emit_shape(chunk))
        return out

    def flush(self) -> AnalyzerOutput:
        out = self._analyse_frames(upto=self.n_frames)
        out.extend(self._enrich_pending(final=True))
        for pid in list(self.run_len):
            ev = self._close_run(pid, self.n_frames)
            if ev:
                out.events.extend(ev)
        return out

    # ----- sprints, top speed, distance ------------------------------------------------------------

    def _slot_ids(self, frame: int) -> list[str]:
        return self.chunks[frame // self.chunk_ticks].slots

    def _analyse_frames(self, upto: int) -> AnalyzerOutput:
        out = AnalyzerOutput()
        raw = self.raw_speed
        for f in range(self.smoothed_upto, upto):
            lo, hi = max(0, f - 1), min(len(raw) - 1, f + 1)
            sm = np.mean(raw[lo : hi + 1], axis=0) * 3.6  # km/h
            slots = self._slot_ids(f)
            for i in range(22):
                pid = slots[i]
                if i % 11 == 0:
                    continue  # goalkeepers are not tracked for sprint badges
                self.cum_dist[pid] = self.cum_dist.get(pid, 0.0) + float(self.step_dist[f][i])
                out.events.extend(self._distance_milestones(pid, i, f))
                kmh = float(sm[i])
                if kmh >= SPRINT_KMH:
                    if pid not in self.run_len:
                        self.run_len[pid], self.run_start[pid] = 0, f
                        self.run_peak[pid], self.run_peak_frame[pid] = 0.0, f
                    self.run_len[pid] += 1
                    if kmh > self.run_peak[pid]:
                        self.run_peak[pid], self.run_peak_frame[pid] = kmh, f
                elif pid in self.run_len:
                    out.events.extend(self._close_run(pid, f))
        self.smoothed_upto = max(self.smoothed_upto, upto)
        return out

    def _distance_milestones(self, pid: str, slot: int, frame: int) -> list[dict]:
        km = self.cum_dist[pid] / 1000.0
        hit = self.milestones_hit.get(pid, 0)
        evs = []
        while hit < len(DISTANCE_MILESTONES_KM) and km >= DISTANCE_MILESTONES_KM[hit]:
            ev = self._make_event(
                "distance_milestone", frame, pid, slot,
                attributes={"km": DISTANCE_MILESTONES_KM[hit]},
            )  # fmt: skip
            evs.append(ev)
            hit += 1
        self.milestones_hit[pid] = hit
        return evs

    def _close_run(self, pid: str, frame: int) -> list[dict]:
        n = self.run_len.pop(pid)
        start = self.run_start.pop(pid)
        peak = self.run_peak.pop(pid)
        peak_f = self.run_peak_frame.pop(pid)
        if n < MIN_SPRINT_FRAMES:
            return []
        slot = self._slot_ids(frame - 1).index(pid) if pid in self._slot_ids(frame - 1) else None
        if slot is None:
            return []
        dist = float(sum(self.step_dist[g][slot] for g in range(start, frame)))
        pos_start = self._pos_at(start, slot)
        pos_peak = self._pos_at(peak_f, slot)
        attrs = {
            "startMs": round(start * 1000 / self.hz),
            "endMs": round(frame * 1000 / self.hz),
            "peakKmh": round(peak, 1),
            "distanceM": round(dist, 1),
        }
        evs = [
            self._make_event("sprint", frame, pid, slot, loc=pos_start, end=pos_peak, attributes=attrs)
        ]
        if peak >= TOP_SPEED_KMH:
            evs.append(
                self._make_event(
                    "top_speed", frame, pid, slot, loc=pos_peak,
                    attributes={"peakKmh": round(peak, 1)},
                )
            )  # fmt: skip
        return evs

    def _pos_at(self, frame: int, slot: int) -> np.ndarray | None:
        ch = self.chunks.get(frame // self.chunk_ticks)
        if ch is None:
            return None
        p = ch.frames[frame % self.chunk_ticks, slot]
        return None if np.isnan(p[0]) else p

    def _make_event(self, type_: str, frame: int, pid: str, slot: int, *, loc=None, end=None, attributes=None) -> dict:
        self.x_counter += 1
        ms = round(frame * 1000 / self.hz)
        if loc is None:
            loc = self._pos_at(max(0, frame - 1), slot)
        ev = {
            "id": f"{self.match_id}-x{self.x_counter:05d}",
            "matchId": self.match_id,
            "seq": 1_000_000 + self.x_counter,
            "type": type_,
            "clock": clock_from_ms(ms, self.p2_start_ms),
            "team": pid.split("-")[0],
            "player": pid,
            "attributes": attributes or {},
            "possessionId": None,
        }
        if loc is not None:
            ev["location"] = {"x": round(float(loc[0]), 1), "y": round(float(loc[1]), 1)}
        if end is not None:
            ev["end"] = {"x": round(float(end[0]), 1), "y": round(float(end[1]), 1)}
        return ev

    # ----- enrichment of passes and shots ----------------------------------------------------------

    def _frame_at(self, frame: int) -> tuple[np.ndarray, np.ndarray, list[str], bool] | None:
        ch = self.chunks.get(frame // self.chunk_ticks)
        if ch is None:
            return None
        k = frame % self.chunk_ticks
        return ch.frames[k], ch.ball[k], ch.slots, bool(ch.alive[k])

    def _ball_speed_kmh(self, frame: int) -> float | None:
        best = 0.0
        prev = self._frame_at(frame)
        if prev is None:
            return None
        for k in range(1, LOOKAHEAD_FRAMES):
            cur = self._frame_at(frame + k)
            if cur is None:
                return None
            if prev[3] and cur[3]:  # ignore the ball being reset during stoppages
                d = cur[1][:2] - prev[1][:2]
                best = max(best, float(np.hypot(d[0], d[1])) / self.dt * 3.6)
            prev = cur
        return best

    def _enrich_pending(self, final: bool = False) -> AnalyzerOutput:
        out = AnalyzerOutput()
        keep = []
        for e in self.pending:
            f_e = round(e["clock"]["matchMs"] * self.hz / 1000)
            ready = f_e + LOOKAHEAD_FRAMES < self.n_frames
            if not ready and not final:
                keep.append(e)
                continue
            doc = self._enrich(e, f_e)
            if doc is not None:
                out.enrichments.append(doc)
        self.pending = keep
        return out

    def _enrich(self, e: dict, f_e: int) -> dict | None:
        fr = self._frame_at(f_e)
        if fr is None:
            return None
        pos = fr[0]
        team_idx = self.clubs.index(e["team"])
        opp = pos[(1 - team_idx) * 11 : (1 - team_idx) * 11 + 11]
        speed = self._ball_speed_kmh(f_e)
        loc = np.array([e["location"]["x"], e["location"]["y"]])
        end = np.array([e["end"]["x"], e["end"]["y"]]) if "end" in e else loc
        physics: dict = {"distanceM": round(float(np.hypot(*(end - loc))), 1)}
        if e["type"] == "pass":
            period = e["clock"]["period"]
            d = self.attack_dirs.get(period, {}).get(e["team"], 1)
            forward = (end[0] - loc[0]) * d
            physics.update(
                {
                    "ballSpeedKmh": round(speed, 1) if speed is not None else None,
                    "pressurePasser": round(pressure_at(loc, opp), 2),
                    "pressureReceiver": round(pressure_at(end, opp), 2),
                    "laneBlock": round(lane_block(loc, end, opp), 2),
                    "forwardM": round(float(forward), 1),
                }
            )
        else:
            d = self.attack_dirs.get(e["clock"]["period"], {}).get(e["team"], 1)
            goal = np.array([G.PITCH_L if d == 1 else 0.0, G.CY])
            blockers = 0
            ab = goal - loc
            l2 = float(ab @ ab)
            for q in opp[1:]:
                if np.isnan(q[0]) or l2 < 1e-6:
                    continue
                tt = float(np.clip(((q - loc) @ ab) / l2, 0.0, 1.0))
                if 0.08 < tt < 0.85 and float(np.hypot(*(q - (loc + tt * ab)))) < 1.5:
                    blockers += 1
            physics.update(
                {
                    "shotSpeedKmh": round(speed, 1) if speed is not None else None,
                    "pressure": round(pressure_at(loc, opp), 2),
                    "blockers": blockers,
                }
            )
        return {
            "id": f"{e['id']}-phys",
            "matchId": e["matchId"],
            "type": "physics",
            "ref": e["id"],
            "clock": e["clock"],
            "physics": physics,
        }

    # ----- team shape -----------------------------------------------------------------------------------

    def _accumulate_shape(self, chunk: Chunk) -> None:
        # Who is closest to the ball in each frame: a tracking-only proxy for possession.
        ball = chunk.ball[:, :2].astype(float)
        d_all = np.hypot(chunk.frames[:, :, 0] - ball[:, None, 0], chunk.frames[:, :, 1] - ball[:, None, 1])
        d_all = np.where(np.isnan(d_all), np.inf, d_all)
        nearest = np.argmin(d_all, axis=1)
        for team in (0, 1):
            club = self.clubs[team]
            sl = slice(team * 11 + 1, team * 11 + 11)
            for k in range(chunk.n):
                f = chunk.first_frame + k
                period = 2 if (2 in self.period_start_frame and f >= self.period_start_frame[2]) else 1
                d = self.attack_dirs.get(period, {}).get(club, 1)
                pts = chunk.frames[k, sl]
                pts = pts[~np.isnan(pts[:, 0])]
                if len(pts) < 5:
                    continue
                ax = pts[:, 0] if d == 1 else G.PITCH_L - pts[:, 0]
                ay = pts[:, 1] if d == 1 else G.PITCH_W - pts[:, 1]
                order = np.sort(ax)
                out_of_possession = bool(chunk.alive[k]) and not (team * 11 <= nearest[k] < team * 11 + 11)
                ball_ax = ball[k, 0] if d == 1 else G.PITCH_L - ball[k, 0]
                press_dist = near8 = None
                # Pressing is judged where it matters: the opponent has the ball in the half we attack.
                if out_of_possession and ball_ax >= G.CX:
                    dd = d_all[k, sl]
                    dd = dd[np.isfinite(dd)]
                    press_dist = float(dd.min())
                    near8 = int((dd <= 8.0).sum())
                in_possession = bool(chunk.alive[k]) and not out_of_possession
                # Defensive shape is only comparable at the same ball height: a line drops when the ball
                # is near the goal whatever the tactics, so sample it with the ball in the middle zone.
                defending_mid = out_of_possession and 35.0 <= ball_ax <= 75.0
                self.shape_acc[team].append(
                    (
                        float(order[:4].mean()),  # defensive line
                        float(order[-3:].mean()),  # front line
                        float(ay.max() - ay.min()),  # width
                        float(ax.mean()),  # centroid
                        press_dist,
                        near8,
                        defending_mid,
                        in_possession,
                    )
                )

    def _emit_shape(self, chunk: Chunk) -> list[dict]:
        evs = []
        end_frame = chunk.first_frame + chunk.n
        for team in (0, 1):
            acc = self.shape_acc[team]
            self.shape_acc[team] = []
            if not acc:
                continue
            a = np.array([r[:4] for r in acc])
            oop = [(r[4], r[5]) for r in acc if r[4] is not None]
            defending = np.array([bool(r[6]) for r in acc])
            attacking = np.array([bool(r[7]) for r in acc])
            self.x_counter += 1
            ms = round(end_frame * 1000 / self.hz)
            attrs = {
                "lineHeightM": round(float(a[:, 0].mean()), 1),
                "frontLineM": round(float(a[:, 1].mean()), 1),
                "widthM": round(float(a[:, 2].mean()), 1),
                "lengthM": round(float((a[:, 1] - a[:, 0]).mean()), 1),
                "centroidM": round(float(a[:, 3].mean()), 1),
                "windowMs": SHAPE_WINDOW_CHUNKS * self.chunk_ticks * 1000 // self.hz,
                "pressFrames": len(oop),
            }
            # Teams change shape with the ball, so shape is also reported per phase: a tactical shift
            # is a change in how the team *defends* (ball in the middle zone) or builds, not in how
            # long it had the ball or where play happened to be.
            for flag, mask in (("Def", defending), ("Ip", attacking)):
                attrs[f"{flag.lower()}Frames"] = int(mask.sum())
                if mask.sum() >= 10:
                    attrs[f"lineHeight{flag}M"] = round(float(a[mask, 0].mean()), 1)
                    attrs[f"width{flag}M"] = round(float(a[mask, 2].mean()), 1)
            if oop:
                # How tightly the team closes the ball down in the opponent's half.
                attrs["pressDistM"] = round(float(np.mean([o[0] for o in oop])), 2)
                attrs["pressNear8"] = round(float(np.mean([o[1] for o in oop])), 2)
            evs.append(
                {
                    "id": f"{self.match_id}-x{self.x_counter:05d}",
                    "matchId": self.match_id,
                    "seq": 1_000_000 + self.x_counter,
                    "type": "team_shape",
                    "clock": clock_from_ms(ms, self.p2_start_ms),
                    "team": self.clubs[team],
                    "player": None,
                    "attributes": attrs,
                    "possessionId": None,
                }
            )
        return evs


def analyze_match(result) -> AnalyzerOutput:
    """Run the analyzer over a finished simulated match (batch mode)."""
    an = PhysicalAnalyzer(result.meta)
    an.add_events(result.events)
    out = AnalyzerOutput()
    for ch in iter_chunks(result):
        out.extend(an.process_chunk(ch))
    out.extend(an.flush())
    out.events.sort(key=lambda e: (e["clock"]["matchMs"], e["seq"]))
    return out


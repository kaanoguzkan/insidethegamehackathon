"""A video frame from tracking: pitch, players in their team colours, the ball (bigger when it is in the air), camera noise.

Top-down, 4 pixels to the metre, so pixel coordinates are a plain scaling of pitch coordinates (a production camera would first estimate a homography from
the pitch lines; the pitch lines are drawn here so that is possible). The renderer is only the stand-in for the video provider.
"""

from __future__ import annotations

import numpy as np

PX = 4  # pixels per metre
MARGIN_M = 2.0
PITCH_L, PITCH_W = 105.0, 68.0
W = int((PITCH_L + 2 * MARGIN_M) * PX)
H = int((PITCH_W + 2 * MARGIN_M) * PX)
PLAYER_R_M = 0.6  # a player seen from above (shoulders)
BALL_R_M = 0.55  # a broadcast camera exaggerates the ball: at 4 px a metre a real one would be about a pixel
HOME = np.array([225, 45, 45], dtype=np.float32)
AWAY = np.array([45, 105, 235], dtype=np.float32)
BALL = np.array([250, 250, 250], dtype=np.float32)
GRASS_A = np.array([38, 118, 52], dtype=np.float32)
GRASS_B = np.array([34, 108, 48], dtype=np.float32)
LINE = np.array([185, 195, 185], dtype=np.float32)


def to_px(x: np.ndarray | float, y: np.ndarray | float) -> tuple:
    return (np.asarray(x) + MARGIN_M) * PX, (np.asarray(y) + MARGIN_M) * PX


def to_m(px: np.ndarray | float, py: np.ndarray | float) -> tuple:
    return np.asarray(px) / PX - MARGIN_M, np.asarray(py) / PX - MARGIN_M


def _background() -> np.ndarray:
    img = np.empty((H, W, 3), dtype=np.float32)
    stripe = (np.arange(W) // (int(7.5 * PX))) % 2
    img[:] = np.where(stripe[None, :, None] == 0, GRASS_A, GRASS_B)

    def hline(y: float, x0: float, x1: float) -> None:
        py = int(round((y + MARGIN_M) * PX))
        px0, px1 = int((x0 + MARGIN_M) * PX), int((x1 + MARGIN_M) * PX)
        img[max(py - 1, 0) : py + 1, px0:px1] = LINE

    def vline(x: float, y0: float, y1: float) -> None:
        px = int(round((x + MARGIN_M) * PX))
        py0, py1 = int((y0 + MARGIN_M) * PX), int((y1 + MARGIN_M) * PX)
        img[py0:py1, max(px - 1, 0) : px + 1] = LINE

    hline(0, 0, PITCH_L); hline(PITCH_W, 0, PITCH_L); vline(0, 0, PITCH_W); vline(PITCH_L, 0, PITCH_W); vline(PITCH_L / 2, 0, PITCH_W)  # noqa: E702
    for x0, x1 in ((0, 16.5), (PITCH_L - 16.5, PITCH_L)):  # the penalty areas
        hline(13.85, x0, x1); hline(PITCH_W - 13.85, x0, x1)  # noqa: E702
        vline(16.5 if x0 == 0 else PITCH_L - 16.5, 13.85, PITCH_W - 13.85)
    yy, xx = np.mgrid[0:H, 0:W]
    d = np.hypot(xx / PX - MARGIN_M - PITCH_L / 2, yy / PX - MARGIN_M - PITCH_W / 2)
    img[np.abs(d - 9.15) < 0.15] = LINE  # the centre circle
    return img


_BG = _background()


def _stamp(img: np.ndarray, cx: float, cy: float, r: float, color: np.ndarray) -> None:
    """An anti-aliased disc of radius ``r`` pixels at pixel ``(cx, cy)``."""
    x0, y0 = int(cx) - int(r) - 2, int(cy) - int(r) - 2
    x1, y1 = x0 + 2 * int(r) + 6, y0 + 2 * int(r) + 6
    if x1 <= 0 or y1 <= 0 or x0 >= W or y0 >= H:
        return
    xs, ys = np.arange(max(x0, 0), min(x1, W)), np.arange(max(y0, 0), min(y1, H))
    d = np.hypot(xs[None, :] + 0.5 - cx, ys[:, None] + 0.5 - cy)
    a = np.clip(r - d + 0.5, 0.0, 1.0)[:, :, None]
    sl = img[ys[0] : ys[-1] + 1, xs[0] : xs[-1] + 1]  # a small window of the uint8 frame: blended in float, written back as uint8
    sl[:] = (sl * (1 - a) + color * a).astype(np.uint8)


_NOISY = np.clip(_BG[None] + np.random.default_rng(7).normal(0.0, 5.0, (6, H, W, 1)), 0, 255).astype(np.uint8)  # the pitch under a few frames of camera noise, shared out frame by frame
BG_MEAN = np.clip(_BG, 0, 255).astype(np.int16)  # the pitch with no players: what a detector subtracts


def render_frame(players: np.ndarray, ball: np.ndarray, rng: np.random.Generator | None = None, noise: float = 5.0) -> np.ndarray:
    """``players``: (22, 2) metres (NaN: off the pitch), slots 0-10 home and 11-21 away; ``ball``: (3,) metres x, y, height. Returns (H, W, 3) uint8."""
    rng = rng or np.random.default_rng(0)
    img = (_NOISY[int(rng.integers(0, len(_NOISY)))] if noise > 0 else _BG.astype(np.uint8)).copy()
    px, py = to_px(players[:, 0], players[:, 1])
    for i in range(22):
        if not np.isnan(px[i]):
            _stamp(img, float(px[i]), float(py[i]), PLAYER_R_M * PX, HOME if i < 11 else AWAY)
    bx, by = to_px(ball[0], ball[1])
    if not np.isnan(bx):
        _stamp(img, float(bx), float(by), BALL_R_M * PX * (1.0 + float(ball[2]) / 5.0), BALL)  # the ball looks bigger the closer to the camera
    return img


def png(img: np.ndarray) -> bytes:
    """A PNG of an RGB image (no imaging library needed)."""
    import struct
    import zlib

    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 3)) + chunk(b"IEND", b"")

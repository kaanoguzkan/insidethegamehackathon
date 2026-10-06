// Display-only spacing: players who stand almost on top of each other in the data are drawn a little apart, so
// two figures never overlap. Nothing here changes the tracking data, the analytics or the graphics drawn on the
// ground; it only moves where a figure or marker is drawn, by at most `maxShift` metres.

export interface Pt {
  x: number
  y: number
}

/**
 * Push apart any two points closer than `minD` metres, keeping `pinned` (the ball carrier) where it is.
 * Deterministic: coincident points are separated along a direction taken from their order.
 */
export function relax(points: Pt[], minD: number, pinned = -1, maxShift = 2.4, passes = 6, screenScale: [number, number] = [1, 1]): Pt[] {
  if (screenScale[0] !== 1 || screenScale[1] !== 1) {
    // A tilted camera squashes one direction on screen (a metre across the pitch looks shorter than a metre along
    // it), so two players need more real metres between them in that direction: work in screen-like space, map back.
    const [sx, sy] = screenScale
    const scaled = relax(points.map((p) => ({ x: p.x * sx, y: p.y * sy })), minD, pinned, maxShift, passes)
    return scaled.map((p, i) => {
      const x = p.x / sx
      const y = p.y / sy
      const d = Math.hypot(x - points[i].x, y - points[i].y)
      return d > maxShift ? { x: points[i].x + ((x - points[i].x) / d) * maxShift, y: points[i].y + ((y - points[i].y) / d) * maxShift } : { x, y }
    })
  }
  const out = points.map((p) => ({ x: p.x, y: p.y }))
  const n = out.length
  for (let pass = 0; pass < passes; pass++) {
    let moved = false
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let dx = out[j].x - out[i].x
        let dy = out[j].y - out[i].y
        let d = Math.hypot(dx, dy)
        if (d >= minD) continue
        if (d < 1e-3) {
          const a = (i * 7 + j * 13) * 0.7 // any fixed direction will do
          dx = Math.cos(a)
          dy = Math.sin(a)
          d = 1
        }
        const push = minD - Math.hypot(out[j].x - out[i].x, out[j].y - out[i].y)
        const ux = dx / d
        const uy = dy / d
        // The pinned player does not move: the other takes the whole push; otherwise share it.
        const wi = i === pinned ? 0 : j === pinned ? 1 : 0.5
        const wj = j === pinned ? 0 : i === pinned ? 1 : 0.5
        out[i].x -= ux * push * wi
        out[i].y -= uy * push * wi
        out[j].x += ux * push * wj
        out[j].y += uy * push * wj
        moved = true
      }
    }
    // Nobody is moved far from where the data has them.
    for (let i = 0; i < n; i++) {
      const sx = out[i].x - points[i].x
      const sy = out[i].y - points[i].y
      const s = Math.hypot(sx, sy)
      if (s > maxShift) {
        out[i].x = points[i].x + (sx / s) * maxShift
        out[i].y = points[i].y + (sy / s) * maxShift
      }
    }
    if (!moved) break
  }
  return out
}

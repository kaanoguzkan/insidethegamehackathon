// Pitch control: the same formula as src/matchmind/tracking/control.py (a test keeps them in step).
// A cell belongs to the team whose nearest player could reach it sooner, blended by a logistic.

export const NX = 21
export const NY = 14
export const VMAX = 7.0
export const K = 2.2
const L = 105
const W = 68

export interface P {
  slot: number
  x: number
  y: number
}

/** P(home team controls each cell), row-major: iy * NX + ix. Slots 0-10 are the home team, 11-21 the away team. */
export function homeControl(players: P[]): Float32Array {
  const out = new Float32Array(NX * NY)
  for (let iy = 0; iy < NY; iy++) {
    const cy = ((iy + 0.5) * W) / NY
    for (let ix = 0; ix < NX; ix++) {
      const cx = ((ix + 0.5) * L) / NX
      let ta = Infinity
      let tb = Infinity
      for (const p of players) {
        const t = Math.hypot(cx - p.x, cy - p.y) / VMAX
        if (p.slot < 11) ta = Math.min(ta, t)
        else tb = Math.min(tb, t)
      }
      const z = Math.max(-30, Math.min(30, K * (tb - ta)))
      out[iy * NX + ix] = 1 / (1 + Math.exp(-z))
    }
  }
  return out
}

/** Share of the pitch the home team controls. */
export const homeShare = (grid: Float32Array) => grid.reduce((a, b) => a + b, 0) / grid.length

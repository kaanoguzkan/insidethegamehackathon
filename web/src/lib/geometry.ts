// Geometry for the live pitch graphics: team shape hulls, the offside line and passing lanes.
import type { Frame, PlayerPoint } from './tracking'

export type Pt = [number, number]

/** Convex hull (monotone chain), counter-clockwise. */
export function convexHull(points: Pt[]): Pt[] {
  const p = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1])
  if (p.length < 3) return p
  const cross = (o: Pt, a: Pt, b: Pt) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
  const lower: Pt[] = []
  for (const q of p) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], q) <= 0) lower.pop()
    lower.push(q)
  }
  const upper: Pt[] = []
  for (const q of [...p].reverse()) {
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], q) <= 0) upper.pop()
    upper.push(q)
  }
  return [...lower.slice(0, -1), ...upper.slice(0, -1)]
}

export const polygonArea = (h: Pt[]) => Math.abs(h.reduce((s, p, i) => s + p[0] * h[(i + 1) % h.length][1] - h[(i + 1) % h.length][0] * p[1], 0)) / 2

const outfield = (players: PlayerPoint[], team: 0 | 1) => players.filter((p) => (p.slot < 11 ? 0 : 1) === team && p.slot % 11 !== 0)

export function teamHull(frame: Frame, team: 0 | 1): Pt[] {
  return convexHull(outfield(frame.players, team).map((p) => [p.x, p.y] as Pt))
}

/** The four deepest outfield players of a team, ordered across the pitch: its defensive line. */
export function defensiveLine(frame: Frame, team: 0 | 1, attackDir: 1 | -1): Pt[] {
  const mine = outfield(frame.players, team)
  const depth = (p: PlayerPoint) => (attackDir === 1 ? p.x : 105 - p.x)
  return mine
    .sort((a, b) => depth(a) - depth(b))
    .slice(0, 4)
    .sort((a, b) => a.y - b.y)
    .map((p) => [p.x, p.y] as Pt)
}

/** x of the offside line for the team that is defending: the second-deepest outfield defender (the keeper is the last). */
export function offsideLineX(frame: Frame, defending: 0 | 1, defenderAttackDir: 1 | -1): number | null {
  const mine = outfield(frame.players, defending)
  if (mine.length < 2) return null
  const depth = (p: PlayerPoint) => (defenderAttackDir === 1 ? p.x : 105 - p.x) // distance from its own goal
  const sorted = [...mine].sort((a, b) => depth(a) - depth(b))
  return sorted[1].x
}

/** How much a pass lane is blocked by opponents: 0 clear, 1 blocked (same rule as the analyzer). */
export function laneBlock(a: Pt, b: Pt, opp: PlayerPoint[]): number {
  const dx = b[0] - a[0]
  const dy = b[1] - a[1]
  const l2 = dx * dx + dy * dy
  if (l2 < 1e-6) return 0
  let best = Infinity
  for (const q of opp) {
    const t = ((q.x - a[0]) * dx + (q.y - a[1]) * dy) / l2
    if (t <= 0.12 || t >= 0.95) continue
    const cx = a[0] + Math.min(1, Math.max(0, t)) * dx
    const cy = a[1] + Math.min(1, Math.max(0, t)) * dy
    best = Math.min(best, Math.hypot(q.x - cx, q.y - cy))
  }
  return best === Infinity ? 0 : Math.max(0, 1 - best / 2.6)
}

export interface Lane {
  to: PlayerPoint
  block: number
  forward: number
}

/** The ball carrier's best passing options: teammates within range, scored by progress and how open the lane is. */
export function passingLanes(frame: Frame, carrier: PlayerPoint, attackDir: 1 | -1, max = 4): Lane[] {
  const team = carrier.slot < 11 ? 0 : 1
  const mates = outfield(frame.players, team).filter((p) => p.slot !== carrier.slot)
  const opp = frame.players.filter((p) => (p.slot < 11 ? 0 : 1) !== team)
  const lanes: Lane[] = []
  for (const m of mates) {
    const d = Math.hypot(m.x - carrier.x, m.y - carrier.y)
    if (d < 6 || d > 38) continue
    lanes.push({ to: m, block: laneBlock([carrier.x, carrier.y], [m.x, m.y], opp), forward: (m.x - carrier.x) * attackDir })
  }
  return lanes.sort((a, b) => b.forward * (1 - b.block) - a.forward * (1 - a.block)).slice(0, max)
}

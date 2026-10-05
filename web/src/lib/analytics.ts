// Types and helpers for analytics.json: the Opta-style views of a match (see src/matchmind/analytics/report.py).

export interface WinPoint {
  matchMs: number
  tag: string
  score: [number, number]
  p: { home: number; draw: number; away: number }
}

export interface Swing {
  matchMs: number
  kind: 'goal' | 'red'
  before: WinPoint['p']
  after: WinPoint['p']
  swing: number
}

export interface ShotRow {
  id: string
  team: string
  player: string
  ms: number
  x: number
  y: number
  xg: number
  xgot: number | null
  outcome: string
  situation?: string | null
  bodyPart?: string | null
  goalMouthY?: number | null
  goalMouthZ?: number | null
}

export interface ActionRow {
  id: string
  player: string | null
  name: string | null
  team: string
  type: string
  ms: number
  value: number
}

export interface PlayerRow {
  id: string
  name: string
  team: string
  pos: string
  goals: number
  assists: number
  shots: number
  xg: number
  keyPasses: number
  xa: number
  passes: number
  passesComplete: number
  tackles: number
  interceptions: number
  pressures: number
  minutes: number | null
  value: number | null
  valueAttacking: number | null
  valueDefending: number | null
  packing: number
  lineBreaks: number
  runs: Record<string, number>
  km: number | null
  hsrM: number | null
  sprintM: number | null
  impact: number
}

export interface NetNode {
  id: string
  name: string | null
  pos: string | null
  x: number
  y: number
  passes: number
}
export interface Network {
  club: string
  nodes: NetNode[]
  edges: { a: string; b: string; n: number }[]
  stats: { completedPasses: number; avgPassLengthM: number | null; avgX: number | null; strongestLink: { a: string; b: string; n: number } | null }
}

export interface Measured {
  label: string
  from: string
  misfit: number
  margin: number
  runnerUp: string | null
}
export interface ShapePhase {
  measured: Measured | null
  players: { id: string; name: string | null; pos: string | null; x: number; y: number }[]
}
export interface TeamShapes {
  nominal: string
  designed: { base: string; attack: string; block: string; blurb?: string } | null
  def: ShapePhase
  ip: ShapePhase
  blocks: { block: number; endMs: number; def: string | null; ip: string | null }[]
}

export interface RoutineStat {
  n: number
  shots: number
  xg: number
  goals: number
}
export interface SetPieceTeam {
  taken: Record<string, Record<string, RoutineStat>>
  conceded: Record<string, RoutineStat>
  defence: string
  goalKickFirstPass: Record<string, { n: number; complete: number; rate: number | null }>
}

export interface Transition {
  lost: number
  regained5s: number
  counterpressRate: number | null
  highTurnovers: number
  highTurnoverShots: number
  fastBreaks: number
  fastBreakGoals: number
  fastBreakXg: number
  quickEntries: number
}

export interface Keeper {
  player: string
  name: string
  shotsFaced: number
  onTarget: number
  saves: number
  goalsConceded: number
  xgotFaced: number
  goalsPrevented: number
  claims: number
  passes: number
  passCompletion: number | null
  longShare: number | null
}

export interface RunRow {
  id: string
  team: string
  player: string
  kind: 'in_behind' | 'overlap' | 'drop'
  distanceM: number
  peakKmh: number
  startMs: number
  endMs: number
  from: [number, number]
  to: [number, number]
  ballPlayed: boolean
}

export interface RadarAxis {
  key: string
  label: string
  value: number | null
  pct: number
}
export interface Radar {
  group: string
  axes: RadarAxis[]
  similar: { id: string; name: string; team: string; similarity: number }[]
}
export interface TeamAxis {
  key: string
  label: string
  value: number | null
  scaled: number
}

export interface StandingRow {
  club: string
  played: number
  won: number
  drawn: number
  lost: number
  gf: number
  ga: number
  gd: number
  pts: number
  pos: number
}
export interface SeasonContext {
  season: string
  round: number
  played: number
  standings: StandingRow[]
  form: Record<string, string>
  streaks: Record<string, { unbeaten: number; winless: number; wins: number; cleanSheets: number; scoredIn: number }>
  headToHead: { record: Record<string, number>; meetings: { season: string; round: number; home: string; away: string; score: [number, number] }[] }
  topScorers: { id: string; name: string | null; goals: number }[]
  records: { fastestGoal: { minute: number; player: string; team: string; season: string } | null; mostGoalsByPlayer: { n: number; player?: string }; biggestWin: { margin: number; home?: string; away?: string; score?: [number, number] }; highestScoring: { goals: number; home?: string; away?: string; score?: [number, number] } }
  prediction: { home: number; draw: number; away: number; xg: Record<string, number>; scores: { score: [number, number]; p: number }[]; strength: Record<string, number> }
  ratings: Record<string, { att: number; def: number; xgFor: number | null; xgAgainst: number | null }>
}

export interface Analytics {
  version: number
  clubs: string[]
  winProbability: { series: WinPoint[]; swings: Swing[]; preMatch: WinPoint['p'] | null; final: WinPoint['p'] | null }
  shots: { shots: ShotRow[]; race: Record<string, [number, number, number][]>; teams: Record<string, { shots: number; onTarget: number; goals: number; xg: number; xgot: number; bigChances: number }> }
  possessionValue: { available: boolean; players?: Record<string, { value: number }>; best?: ActionRow[]; worst?: ActionRow[] }
  networks: Record<string, { full: Network; h1: Network; h2: Network }>
  shapes: Record<string, TeamShapes>
  space: { series: Record<string, { ms: number; control: number; finalThird: number; behind: number | null; block?: number | null }[]>; teams: Record<string, { controlShare: number | null; finalThirdControl: number | null; spaceBehindM2: number | null; blockAreaM2?: number | null }> }
  lineBreaks: { teams: Record<string, { completed: number; packing: number; lineBreaks: number; threeLines: number }>; best: { id: string; team: string; player: string; receiver: string | null; ms: number; bypassed: number; lines: number }[] }
  runs: { runs: RunRow[]; teams: Record<string, Record<string, { n: number; ballPlayed: number }>> }
  load: { players: Record<string, { km: number; hsrM: number; sprintM: number; acc: number; dec: number; minutes: number; fatigue: number | null; name: string; team: string }>; top: { id: string; name: string; team: string; km: number; hsrM: number; sprintM: number; acc: number; dec: number }[] }
  setPieces: { teams: Record<string, SetPieceTeam> }
  transitions: Record<string, Transition>
  goalkeepers: Record<string, Keeper>
  pressing: Record<string, { pressures: number; ppdaByZone: Record<string, number | null>; zoneShare: Record<string, number>; triggerShare: Record<string, number> }>
  players: PlayerRow[]
  playerOfTheMatch: PlayerRow | null
  season?: SeasonContext
  radars?: Record<string, Radar>
  teamRadars?: Record<string, TeamAxis[]>
}

/** Win probability at a match time, interpolated between the minute ticks (goals and cards step). */
export function winProbAt(a: Analytics | null | undefined, ms: number): WinPoint['p'] | null {
  const s = a?.winProbability.series
  if (!s || !s.length) return null
  let lo = 0
  let hi = s.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (s[mid].matchMs <= ms) lo = mid
    else hi = mid - 1
  }
  const a0 = s[lo]
  const a1 = s[Math.min(lo + 1, s.length - 1)]
  if (a1.matchMs === a0.matchMs || a1.tag.startsWith('after') || a0.tag.startsWith('after')) return a0.p
  const f = (ms - a0.matchMs) / (a1.matchMs - a0.matchMs)
  return {
    home: a0.p.home + (a1.p.home - a0.p.home) * f,
    draw: a0.p.draw + (a1.p.draw - a0.p.draw) * f,
    away: a0.p.away + (a1.p.away - a0.p.away) * f,
  }
}

export const pct = (v: number, digits = 0) => `${(v * 100).toFixed(digits)}%`

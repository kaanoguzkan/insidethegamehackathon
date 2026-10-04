// Shapes of the replay package, mirroring schemas/*.schema.json and the interpreter's evidence packs.

export type Mode = 'analyst' | 'casual'
export type Lang = 'en' | 'es' | 'tr'

export interface Cohort {
  mode: Mode | 'any'
  language: Lang
  perspective: string
  focusPlayer: string | null
}

export interface Chip {
  label: string
  value: string
}

export interface Overlay {
  id: string
  matchId: string
  momentId?: string | null
  factId?: string | null
  kind: string
  displayAt: { matchMs: number }
  durationMs: number
  priority: number
  cohort: Cohort
  content: { headline: string; body: string; chips: Chip[] }
  anchor: { type: 'screen' | 'player'; region?: string | null; player?: string | null }
  provenance: { agents: string[]; verified: boolean; evidenceRef?: string | null; fallbackLevel: number; model?: string | null }
  schemaVersion: string
}

export interface MetricChange {
  before?: number | null
  after?: number | null
  delta?: number
  changePct?: number
  consistent?: boolean | null
  value?: number | null
}

export interface Explanation {
  what: string
  why: string
  so_what: string
  claims: { text: string; refs: string[] }[]
  tactical_tag: string
  confidence: 'low' | 'medium' | 'high'
  caveats: string[]
}

export interface Moment {
  id: string
  type: string
  detectedAt: { matchMs: number; label: string; clock: { period: number; minute: number; second: number; matchMs: number } }
  salience: number
  subjectTeam: string | null
  beneficiaryTeam: string | null
  teamNames: Record<string, string>
  teamShort: Record<string, string>
  windows: Record<string, { range: [number, number]; label: string }>
  metrics: Record<string, MetricChange>
  facts: Record<string, unknown>
  eventIds: string[]
  players: { id: string; name: string; team: string; pos: string }[]
  glossary: Record<string, string>
  status?: string | null
  level?: number | null
  explanation?: Explanation | null
  explanations?: Partial<Record<Lang, Explanation>>
  variants?: Record<string, { level?: number | null; trace: { agent: string; outcome: string; issues?: string[] }[] }>
  trace: { agent: string; outcome: string; issues?: string[] }[]
}

export interface Snapshot {
  id: string
  matchMs: number
  clock: { period: number; minute: number; second: number }
  momentum: Record<string, number>
  control: { controller: string; share: Record<string, number> }
  chaos: number
  pressure: Record<string, number>
  possession: Record<string, number>
  score: Record<string, number>
}

export interface TeamMeta {
  id: string
  name: string
  short: string
  colors: { primary: string; secondary: string }
  formation: string
  lineup: string[]
  players: Record<string, { name: string; pos: string; number: number }>
}

export interface Meta {
  matchId: string
  scenario: string | null
  hz: number
  frames: number
  home: TeamMeta
  away: TeamMeta
  periods: { period: number; startMs: number; endMs: number; startFrame: number; attackDirection: Record<string, number> }[]
  score: Record<string, number>
  package: { llm: string; cohorts: string[]; levels: Record<string, number>; moments: number; overlays: number; variants?: Record<string, Record<string, number>> }
}

export interface MatchEvent {
  id: string
  type: string
  clock: { period: number; minute: number; second: number; matchMs: number }
  team?: string | null
  player?: string | null
  receiver?: string | null
  location?: { x: number; y: number }
  end?: { x: number; y: number }
  outcome?: string
  kind?: string
}

export interface ReplayIndexEntry {
  id: string
  title: string
  score: Record<string, number>
  home: string
  away: string
  moments: number
  overlays: number
}

export interface Profile {
  mode: Mode
  language: Lang
  perspective: string // 'neutral' or a club id
  focusPlayer: string | null
  density: 'low' | 'medium' | 'high'
  audioDescribed: boolean
  reducedMotion: boolean
  highContrast: boolean
}

export const DEFAULT_PROFILE: Profile = {
  mode: 'casual',
  language: 'en',
  perspective: 'neutral',
  focusPlayer: null,
  density: 'medium',
  audioDescribed: false,
  reducedMotion: false,
  highContrast: false,
}

export interface Recap {
  cohort: string
  kind: 'preview' | 'half_time' | 'full_time'
  headline: string
  summary: string
  key_moments: { momentId: string; label: string; text: string }[]
  player_of_the_match: { id: string; goals: number; assists: number; shots: number } | null
  stats: Chip[]
  provenance: { agents: string[]; verified: boolean; fallbackLevel: number }
}

// Tactics shown in the UI: the formation a team is in at a given time, how it plays (tags) and the set
// pieces it has taken so far. Everything is read from the replay's meta and events; nothing is computed
// from the model.
import type { Replay } from './data'
import type { MatchEvent, Shapes, TeamMeta } from './types'

export interface FormationNow {
  name: string
  attack: string | null
  block: string | null
  build: string | null
  press: string | null
  rest: string | null
  changed: boolean
}

/** The team's formation at `ms`: its starting shape until a formation_change event, then the new one. */
export function formationAt(replay: Replay, team: TeamMeta, ms: number): FormationNow {
  const start: Shapes | undefined = team.shapes
  let now: FormationNow = {
    name: team.startFormation ?? team.formation,
    attack: start?.attack ?? null,
    block: start?.block ?? null,
    build: start?.build ?? null,
    press: start?.press ?? null,
    rest: start?.rest ?? null,
    changed: false,
  }
  for (const e of replay.events) {
    if (e.clock.matchMs > ms) break
    if (e.type === 'formation_change' && e.team === team.id) {
      const a = e.attributes ?? {}
      now = {
        name: String(a.formation ?? now.name),
        attack: typeof a.attack === 'string' ? a.attack : null,
        block: typeof a.block === 'string' ? a.block : null,
        build: typeof a.build === 'string' ? a.build : null,
        press: typeof a.press === 'string' ? a.press : null,
        rest: typeof a.rest === 'string' ? a.rest : null,
        changed: true,
      }
    }
  }
  return now
}

export type TagKey = 'fullbacks' | 'pivot' | 'striker' | 'build_up' | 'corners' | 'corner_defence' | 'long_throws' | 'press_scheme' | 'on_loss' | 'on_win'

const DEFAULTS: Record<TagKey, string | boolean> = {
  fullbacks: 'hold',
  pivot: 'stay',
  striker: 'target',
  build_up: 'mixed',
  corners: 'mixed',
  corner_defence: 'zonal',
  long_throws: false,
  press_scheme: 'zonal',
  on_loss: 'counterpress',
  on_win: 'counter',
}

/** The club's notable tactic tags as i18n keys (`tag.fullbacks.overlap` ...). Defaults are not worth showing. */
export function tagKeys(team: TeamMeta): string[] {
  const style = team.style ?? {}
  const keys: string[] = []
  for (const k of Object.keys(DEFAULTS) as TagKey[]) {
    const v = style[k]
    if (v === undefined) continue
    if (k === 'long_throws') {
      if (v === true) keys.push('tag.long_throws')
    } else if (k === 'corner_defence' || v !== DEFAULTS[k]) {
      keys.push(`tag.${k}.${String(v)}`)
    }
  }
  return keys
}

export interface SetPieceCounts {
  corners: Record<string, number>
  freeKicks: { direct: number; cross: number }
  longThrows: number
  goalKicks: { short: number; long: number }
}

export function setPieceCounts(events: MatchEvent[], teamId: string, ms: number): SetPieceCounts {
  const c: SetPieceCounts = { corners: {}, freeKicks: { direct: 0, cross: 0 }, longThrows: 0, goalKicks: { short: 0, long: 0 } }
  for (const e of events) {
    if (e.clock.matchMs > ms) break
    if (e.team !== teamId) continue
    const r = e.attributes?.routine
    if (typeof r !== 'string') continue
    if (e.type === 'corner') c.corners[r] = (c.corners[r] ?? 0) + 1
    else if (e.type === 'free_kick' && (r === 'direct' || r === 'cross')) c.freeKicks[r] += 1
    else if (e.type === 'throw_in' && r === 'long') c.longThrows += 1
    else if (e.type === 'goal_kick' && (r === 'short' || r === 'long')) c.goalKicks[r] += 1
  }
  return c
}

export function totalCorners(c: SetPieceCounts): number {
  return Object.values(c.corners).reduce((a, b) => a + b, 0)
}

export const CORNER_ORDER = ['near', 'far', 'short', 'edge'] as const

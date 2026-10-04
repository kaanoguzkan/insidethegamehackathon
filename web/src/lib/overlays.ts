import { covers } from './cohort'
import type { Cohort, Overlay, Profile } from './types'

/** What a viewer's density setting lets through. Lower number = more important. */
const MAX_PRIORITY = { low: 2, medium: 3, high: 5 } as const
// Always-on meters follow the density setting too, but are the first thing medium viewers keep.
const KIND_MIN_DENSITY: Record<string, 'low' | 'medium' | 'high'> = {
  momentum_bar: 'medium',
  control_meter: 'high',
  speed_badge: 'high',
  player_tag: 'high',
  ticker: 'medium',
}
const ORDER = { low: 0, medium: 1, high: 2 } as const

export function isShown(o: Overlay, p: Profile, viewer: Cohort): boolean {
  if (!covers(o.cohort, viewer)) return false
  const need = KIND_MIN_DENSITY[o.kind]
  if (need && ORDER[p.density] < ORDER[need]) return false
  if (!need && o.priority > MAX_PRIORITY[p.density]) return false
  // Player-focus viewers see their player's badges and tags; others do not need every one.
  if (o.anchor.type === 'player' && p.focusPlayer && o.anchor.player !== p.focusPlayer && o.kind === 'player_tag') return false
  return true
}

export function activeAt(all: Overlay[], ms: number): Overlay[] {
  return all.filter((o) => o.displayAt.matchMs <= ms && ms < o.displayAt.matchMs + o.durationMs)
}

export function visibleOverlays(all: Overlay[], ms: number, p: Profile, viewer: Cohort): Overlay[] {
  return activeAt(all, ms).filter((o) => isShown(o, p, viewer))
}

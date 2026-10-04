import type { Cohort, Profile } from './types'

/** Mirrors Cohort.covers() in src/matchmind/core/contracts.py. */
export function covers(overlay: Cohort, viewer: Cohort): boolean {
  return (
    overlay.language === viewer.language &&
    (overlay.mode === 'any' || overlay.mode === viewer.mode) &&
    (overlay.perspective === 'neutral' || overlay.perspective === viewer.perspective) &&
    (overlay.focusPlayer === null || overlay.focusPlayer === viewer.focusPlayer)
  )
}

export function cohortOf(p: Profile): Cohort {
  return { mode: p.mode, language: p.language, perspective: p.perspective, focusPlayer: p.focusPlayer }
}

import type { Cohort, Meta, Profile } from './types'

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

/**
 * The viewer's cohort as the Brain will accept it for this match. The club and the followed player live in the URL, so they survive a
 * change of match; the Brain refuses a club or player the match does not have (those fields go into a model prompt), so anything
 * foreign to this match is dropped here and the viewer is treated as neutral.
 */
export function cohortForMatch(p: Profile, meta: Meta): Cohort {
  const clubs = new Set([meta.home.id, meta.away.id])
  const players = new Set([...Object.keys(meta.home.players), ...Object.keys(meta.away.players)])
  return {
    mode: p.mode,
    language: p.language,
    perspective: clubs.has(p.perspective) ? p.perspective : 'neutral',
    focusPlayer: p.focusPlayer && players.has(p.focusPlayer) ? p.focusPlayer : null,
  }
}

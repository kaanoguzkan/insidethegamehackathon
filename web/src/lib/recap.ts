import type { Profile, Recap } from './types'

export const RECAP_KINDS = ['preview', 'half_time', 'full_time'] as const

/** The recap written for this viewer: an exact cohort match, else the neutral one for their mode and language. */
export function recapFor(recaps: Recap[], kind: Recap['kind'], p: Profile): Recap | undefined {
  const exact = `${p.mode}/${p.language}/${p.perspective}/-`
  const neutral = `${p.mode}/${p.language}/neutral/-`
  return recaps.find((r) => r.kind === kind && r.cohort === exact) ?? recaps.find((r) => r.kind === kind && r.cohort === neutral)
}

/** A recap is only available once the match clock has reached it (previews always are). */
export function recapReady(kind: Recap['kind'], ms: number, halfMs: number, endMs: number): boolean {
  return kind === 'preview' || (kind === 'half_time' && ms >= halfMs) || (kind === 'full_time' && ms >= endMs)
}

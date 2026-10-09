import { SAFE_ID } from './data'
import type { Cohort, Overlay } from './types'

/** The Brain API (Azure Container Apps). Empty means the build has none, and the app plays recorded replays only. */
export const BRAIN_URL: string = ((import.meta.env.VITE_BRAIN_URL as string | undefined) ?? '').replace(/\/+$/, '')
export const brainConfigured = BRAIN_URL !== ''

/** The API bounds itself to 5 s; this is only the browser's safety net, with room for the network and a cold start. */
const REQUEST_TIMEOUT_MS = 12_000
/** A Container App that scaled to zero needs a while to start. */
const WAKE_TIMEOUT_MS = 60_000

/** Mirrors Cohort.key in src/matchmind/core/contracts.py. */
export const cohortKey = (c: Cohort): string => `${c.mode}/${c.language}/${c.perspective}/${c.focusPlayer ?? '-'}`

export interface BeatStats {
  cacheHits: number
  modelCalls: number
  repaired: number
  rejected: number
  missedDeadline: number
}

export interface LiveResult {
  momentId: string
  overlays: Overlay[]
  elapsedMs: number
  stats: BeatStats | null
}

/** Fire-and-forget: starts the service if it is asleep, so it is awake by the time someone asks for a live answer. */
export function prewarm(base = BRAIN_URL): void {
  if (base) void fetch(`${base}/health`, { mode: 'cors' }).catch(() => undefined)
}

/** Waits for the service to answer its health check. True when it is up and uses a model. */
export async function wakeBrain(base = BRAIN_URL, signal?: AbortSignal): Promise<boolean> {
  const limit = AbortSignal.timeout(WAKE_TIMEOUT_MS)
  try {
    const res = await fetch(`${base}/health`, { signal: signal ? AbortSignal.any([signal, limit]) : limit })
    return res.ok
  } catch {
    return false
  }
}

/** Overlays for one moment and the given viewer cohorts, written by the model now. */
export async function requestBeats(momentId: string, matchId: string, cohorts: Cohort[], base = BRAIN_URL, signal?: AbortSignal): Promise<LiveResult> {
  if (!SAFE_ID.test(matchId) || !SAFE_ID.test(momentId)) throw new Error('invalid id')
  const limit = AbortSignal.timeout(REQUEST_TIMEOUT_MS)
  const res = await fetch(`${base}/api/beats`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ match_id: matchId, moment_ids: [momentId], cohorts, budget: 1, mode: 'fast', deadlineMs: 5000 }),
    signal: signal ? AbortSignal.any([signal, limit]) : limit,
  })
  if (!res.ok) throw new Error(`brain: ${res.status}`)
  const body = (await res.json()) as { elapsedMs: number; stats?: BeatStats | null; beats: { overlays: Overlay[] }[] }
  return { momentId, overlays: body.beats.flatMap((b) => b.overlays), elapsedMs: body.elapsedMs, stats: body.stats ?? null }
}

/**
 * The recorded overlays with live ones swapped in. A live overlay replaces the recorded lower third for the same
 * moment and cohort only if a model wrote it (fallback level 0 or 1): live template text is no better than the
 * recorded text, and it must not replace model text that was recorded earlier.
 */
export function mergeLive(base: Overlay[], results: Iterable<LiveResult>): Overlay[] {
  const replaced = new Set<string>()
  const added: Overlay[] = []
  for (const r of results) {
    for (const o of r.overlays) {
      if (o.kind !== 'lower_third' || o.provenance.fallbackLevel >= 2) continue
      replaced.add(`${o.momentId}|${cohortKey(o.cohort)}`)
      added.push(o)
    }
  }
  if (added.length === 0) return base
  const kept = base.filter((o) => !(o.kind === 'lower_third' && replaced.has(`${o.momentId}|${cohortKey(o.cohort)}`)))
  return [...kept, ...added].sort((a, b) => a.displayAt.matchMs - b.displayAt.matchMs || a.priority - b.priority)
}

import { BRAIN_URL } from './brain'
import { SAFE_ID } from './data'
import type { ChunkJson, TrackingSource } from './tracking'
import type { Meta, Moment, Overlay } from './types'
import type { Replay } from './data'

/** The live pipeline as the Brain serves it (src/matchmind/live/api.py). */

export interface LiveTeam {
  id: string
  name: string
  short: string
}

export interface LiveMatch {
  matchId: string
  status: 'scheduled' | 'live' | 'finished' | null
  scenario?: string | null
  speed?: number | null
  fromMs?: number | null
  wallStartMs?: number | null
  durationMs?: number | null
  clockMs: number
  serverNowMs: number
  home?: LiveTeam
  away?: LiveTeam
  players?: Record<string, string>
}

export interface LiveEvent {
  n: number
  arrivalMs: number
  id: string
  type: string
  clock: { period: number; minute: number; second: number; matchMs: number }
  team?: string | null
  player?: string | null
  outcome?: string | null
}

export interface LiveMoment {
  id: string
  type: string
  label?: string | null
  salience: number
  detectedAt: { matchMs: number }
  subjectTeam?: string | null
  /** Wall time at which the interpreter stored the moment. */
  createdMs?: number | null
}

export type LiveOverlay = Overlay & { emittedMs: number }

export interface LiveFeed extends LiveMatch {
  events: LiveEvent[]
  eventCursor: number
  more: boolean
  overlays: LiveOverlay[]
  overlayCursor: number
  moments: LiveMoment[]
}

export interface LiveConfig {
  /** The Function app's `/api` address where browsers connect for SignalR pushes; null when the deployment has none. */
  push: string | null
  /** How far behind the live feed viewers watch, in wall seconds: time for the pipeline to write what they are about to see. */
  delayS: number
}

export class LiveBusy extends Error {
  constructor(public matchId: string) {
    super('a live match is already running')
  }
}

const json = async <T>(res: Response): Promise<T> => {
  if (!res.ok) throw new Error(`brain: ${res.status}`)
  return (await res.json()) as T
}

export const listLive = (base = BRAIN_URL, signal?: AbortSignal): Promise<LiveMatch[]> =>
  fetch(`${base}/api/live`, { signal }).then((r) => json<LiveMatch[]>(r))

export function getFeed(matchId: string, event: number, since: number, base = BRAIN_URL, signal?: AbortSignal): Promise<LiveFeed> {
  if (!SAFE_ID.test(matchId)) return Promise.reject(new Error('invalid id'))
  return fetch(`${base}/api/live/${matchId}/feed?event=${event}&since=${since}`, { signal }).then((r) => json<LiveFeed>(r))
}

/** Start the simulator job on a scenario. A match that is already running comes back as a LiveBusy carrying its id, so the visitor joins it. */
export async function startLive(scenario: string, fromMinute: number, base = BRAIN_URL, signal?: AbortSignal): Promise<{ matchId: string }> {
  const res = await fetch(`${base}/api/live/start`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ scenario, fromMinute }), signal })
  if (res.status === 409) {
    const body = (await res.json()) as { detail?: { matchId?: string } }
    if (body.detail?.matchId) throw new LiveBusy(body.detail.matchId)
  }
  if (res.status === 429) throw new Error('rate')
  return json<{ matchId: string }>(res)
}

/** Where the match clock stands now, in match ms: the server's reading advanced by the wall time since it was taken. */
export function liveClock(m: Pick<LiveMatch, 'status' | 'clockMs' | 'speed' | 'durationMs' | 'fromMs'>, receivedAt: number, now: number): number {
  if (m.status === 'finished') return m.durationMs ?? m.clockMs
  if (m.status !== 'live') return m.fromMs ?? 0
  const t = m.clockMs + Math.max(0, now - receivedAt) * (m.speed ?? 1)
  return Math.min(t, m.durationMs ?? t)
}

/** The score from the goals seen so far (an own goal is credited to the club the event names, as the feed does). */
export function scoreOf(events: LiveEvent[], home?: string, away?: string): [number, number] {
  let h = 0
  let a = 0
  for (const e of events) {
    if (e.type !== 'goal') continue
    if (e.team === home) h++
    else if (e.team === away) a++
  }
  return [h, a]
}

/** 'minute:second' of a match clock reading in ms ('45+' style stoppage is not tracked: the feed's own clock labels it). */
export function clockLabel(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/**
 * How long each narrative overlay took, in wall seconds, from the moment the feed reached the point where the interpreter could detect it to the
 * moment its overlay was stored. Match time becomes wall time through the match's speed. Moments from before the start of the run (a late join
 * replays the past at once) have no meaningful wall time and are left out.
 */
export function pipelineDelays(m: Pick<LiveMatch, 'wallStartMs' | 'speed' | 'fromMs'>, moments: LiveMoment[], overlays: LiveOverlay[]): number[] {
  if (!m.wallStartMs || !m.speed) return []
  const from = m.fromMs ?? 0
  const firstStory = new Map<string, number>()
  for (const o of overlays) {
    if (o.kind !== 'lower_third' || !o.momentId) continue
    const at = firstStory.get(o.momentId)
    if (at === undefined || o.emittedMs < at) firstStory.set(o.momentId, o.emittedMs)
  }
  const out: number[] = []
  for (const mo of moments) {
    const emitted = firstStory.get(mo.id)
    if (emitted === undefined || mo.detectedAt.matchMs < from) continue
    const happened = m.wallStartMs + (mo.detectedAt.matchMs - from) / m.speed
    out.push(Math.max(0, (emitted - happened) / 1000))
  }
  return out
}

export function median(xs: number[]): number | null {
  if (xs.length === 0) return null
  const s = [...xs].sort((a, b) => a - b)
  const mid = Math.floor(s.length / 2)
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2
}

/** Who wrote an overlay: the model (verified first time), the model after the Verifier's repair, or the template. */
export function writer(o: Overlay): 'model' | 'mended' | 'template' {
  return o.provenance.fallbackLevel === 0 ? 'model' : o.provenance.fallbackLevel === 1 ? 'mended' : 'template'
}

export const getConfig = (base = BRAIN_URL, signal?: AbortSignal): Promise<LiveConfig> => fetch(`${base}/api/live/config`, { signal }).then((r) => json<LiveConfig>(r))

export function getMeta(matchId: string, base = BRAIN_URL, signal?: AbortSignal): Promise<Meta> {
  if (!SAFE_ID.test(matchId)) return Promise.reject(new Error('invalid id'))
  return fetch(`${base}/api/live/${matchId}/meta`, { signal }).then((r) => json<Meta>(r))
}

/** One tracking chunk, or null while it has not been published (the Brain answers 404 until the simulator job has written it). */
export async function getChunk(matchId: string, index: number, base = BRAIN_URL, signal?: AbortSignal): Promise<ChunkJson | null> {
  if (!SAFE_ID.test(matchId)) throw new Error('invalid id')
  const res = await fetch(`${base}/api/live/${matchId}/chunks/${index}`, { signal })
  if (res.status === 404) return null
  return json<ChunkJson>(res)
}

/** The pieces the pitch components read from a replay, for a match that is still being played: tracking that grows, moments and overlays supplied separately. */
export function liveReplay(id: string, meta: Meta, tracking: TrackingSource, moments: LiveMoment[]): Replay {
  return { id, meta, moments: moments as unknown as Moment[], overlays: [], snapshots: [], recaps: [], events: [], eventsById: new Map(), tracking, analytics: null }
}

/**
 * Where the time between a moment and its overlay goes, in wall seconds, for each moment that has a story: from the moment being detectable (match time
 * turned into wall time through the speed) to its being stored by the interpreter (``createdMs``), and from there to its first overlay being stored.
 * A moment with no creation time (older runs) is left out.
 */
export function stageDelays(m: Pick<LiveMatch, 'wallStartMs' | 'speed' | 'fromMs'>, moments: LiveMoment[], overlays: LiveOverlay[]): { interpret: number[]; write: number[] } {
  const out = { interpret: [] as number[], write: [] as number[] }
  if (!m.wallStartMs || !m.speed) return out
  const from = m.fromMs ?? 0
  const first = new Map<string, number>()
  for (const o of overlays) {
    if ((o.kind !== 'lower_third' && o.kind !== 'ticker') || !o.momentId) continue
    const at = first.get(o.momentId)
    if (at === undefined || o.emittedMs < at) first.set(o.momentId, o.emittedMs)
  }
  for (const mo of moments) {
    const emitted = first.get(mo.id)
    if (emitted === undefined || mo.createdMs == null || mo.detectedAt.matchMs < from) continue
    const happened = m.wallStartMs + (mo.detectedAt.matchMs - from) / m.speed
    out.interpret.push(Math.max(0, (mo.createdMs - happened) / 1000))
    out.write.push(Math.max(0, (emitted - mo.createdMs) / 1000))
  }
  return out
}

/** What the page shows is `delayS` seconds behind the live feed, in match time (never before the start of the match). */
export function playClock(liveMs: number, speed: number | null | undefined, delayS: number): number {
  return Math.max(0, liveMs - delayS * 1000 * (speed ?? 1))
}

import type { Analytics } from './analytics'
import { BRAIN_URL } from './brain'
import { SAFE_ID, type Replay } from './data'
import type { ChunkJson, TrackingSource } from './tracking'
import type { Cohort, MatchEvent, Meta, Moment, Overlay, Recap, Snapshot } from './types'

/**
 * A match of your own, played and interpreted inside the Brain (src/matchmind/live/stream_api.py), seen from the match center.
 *
 * The feed answers "what is new since these cursors"; :func:`mergeFeed` keeps what has arrived and :func:`toReplay` presents it as the same
 * ``Replay`` the recorded matches use, so the pitch, overlays, moment list and evidence drawer need no second implementation. What the browser
 * holds is only what the match clock has reached: the server never sends a viewer's future.
 */

/** Where a live match can start: kick-off, or the middle of the match (what happened before is already there, as for a viewer who joins late). */
export const STREAM_STARTS = [0, 44] as const

/** Speeds a viewer can pick (match seconds per wall second). */
export const STREAM_SPEEDS = [1, 5, 10] as const

/** How far behind the feed the picture runs, in wall seconds: time for the pipeline to write what the viewer is about to see (a broadcast delay). */
export const LIVE_DELAY_S = 6

export interface StreamSummary {
  matchId: string
  status: 'scheduled' | 'live' | 'finished' | 'stopped' | 'failed' | null
  speed: number
  fromMs: number
  wallStartMs: number | null
  durationMs: number
  clockMs: number
  serverNowMs: number
  home?: { id: string; name: string; short: string }
  away?: { id: string; name: string; short: string }
}

export type StreamOverlay = Overlay & { emittedMs: number }

export interface StreamFeed extends StreamSummary {
  events: (MatchEvent & { n: number; arrivalMs: number })[]
  eventCursor: number
  more: boolean
  overlays: StreamOverlay[]
  overlayCursor: number
  moments: Moment[]
  momentCursor: number
  snapshots: Snapshot[]
  snapshotCursor: number
  /** The analytics summary of the match so far, present only when newer than the version asked for. */
  analytics?: Analytics
  analyticsVersion: number
  recaps: Recap[]
  recapCursor: number
}

export interface StreamDemo {
  id: string
  home: { id: string; name: string; short: string }
  away: { id: string; name: string; short: string }
}

export class StreamGone extends Error {
  constructor() {
    super('the stream is gone')
  }
}
export class StreamBusy extends Error {
  constructor() {
    super('too many matches are being played')
  }
}
export class StreamRate extends Error {
  constructor() {
    super('too many starts in a minute')
  }
}

async function call<T>(res: Response): Promise<T> {
  if (res.status === 404) throw new StreamGone()
  if (res.status === 503) throw new StreamBusy()
  if (res.status === 429) throw new StreamRate()
  if (!res.ok) throw new Error(`brain: ${res.status}`)
  return (await res.json()) as T
}

const post = (url: string, body: unknown, signal?: AbortSignal) =>
  fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body), signal })

export const listStreamDemos = (base = BRAIN_URL, signal?: AbortSignal) =>
  fetch(`${base}/api/stream/demos`, { signal }).then((r) => call<{ speeds: number[]; demos: StreamDemo[] }>(r))

export async function startStream(demo: string, speed: number, cohorts: Cohort[], fromMinute = 0, base = BRAIN_URL, signal?: AbortSignal): Promise<{ streamId: string } & StreamSummary> {
  if (!SAFE_ID.test(demo)) throw new Error('invalid match id')
  return call(await post(`${base}/api/stream`, { demo, speed, fromMinute, cohorts: cohorts.slice(0, 2) }, signal))
}

export const addStreamCohort = (id: string, cohort: Cohort, base = BRAIN_URL, signal?: AbortSignal) => post(`${base}/api/stream/${id}/cohorts`, cohort, signal).then((r) => call<{ cohort: string }>(r))

export const stopStream = (id: string, base = BRAIN_URL) => fetch(`${base}/api/stream/${id}`, { method: 'DELETE', keepalive: true }).catch(() => undefined)

export const getStreamMeta = (id: string, base = BRAIN_URL, signal?: AbortSignal) => fetch(`${base}/api/stream/${id}/meta`, { signal }).then((r) => call<Meta>(r))

export function getStreamFeed(id: string, c: Cursors, base = BRAIN_URL, signal?: AbortSignal): Promise<StreamFeed> {
  const q = `event=${c.event}&since=${c.since}&full=1&msince=${c.msince}&snap=${c.snap}&av=${c.av}&rv=${c.rv}`
  return fetch(`${base}/api/stream/${id}/feed?${q}`, { signal }).then((r) => call<StreamFeed>(r))
}

export async function getStreamChunk(id: string, index: number, base = BRAIN_URL, signal?: AbortSignal): Promise<ChunkJson | null> {
  const res = await fetch(`${base}/api/stream/${id}/chunks/${index}`, { signal })
  if (res.status === 404) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string }
    if (body.detail && body.detail.startsWith('unknown stream')) throw new StreamGone()
    return null // not published yet
  }
  return call<ChunkJson>(res)
}

// ----- what has arrived -----------------------------------------------------------------------------------

export interface Cursors {
  event: number
  since: number
  msince: number
  snap: number
  av: number
  rv: number
}

export interface StreamData {
  summary: StreamSummary | null
  /** Wall time at which ``summary.clockMs`` was read, so the clock can run on between polls. */
  receivedAt: number
  cursors: Cursors
  events: (MatchEvent & { n: number })[]
  moments: Map<string, Moment>
  overlays: Map<string, Overlay>
  snapshots: Snapshot[]
  analytics: Analytics | null
  recaps: Recap[]
  /** Bumped whenever anything changed, so the caller rebuilds the replay only then. */
  version: number
}

export const emptyStream = (): StreamData => ({
  summary: null, receivedAt: 0, cursors: { event: -1, since: 0, msince: 0, snap: 0, av: 0, rv: 0 }, events: [], moments: new Map(), overlays: new Map(), snapshots: [], analytics: null, recaps: [], version: 0,
})

/** Keep what a feed page carried (repeats are dropped by id, so a page asked for twice changes nothing). Mutates and returns ``d``. */
export function mergeFeed(d: StreamData, f: StreamFeed, now: number): StreamData {
  const { events, overlays, moments, snapshots, analytics, recaps, ...rest } = f
  let changed = d.summary === null || d.summary.status !== f.status
  const prev = d.cursors.event
  for (const e of events) {
    if (e.n > prev) {
      d.events.push(e)
      changed = true
    }
  }
  for (const m of moments) {
    if (!d.moments.has(m.id)) changed = true
    // The evidence pack has no model-written explanation or agent trace: the story is the overlay.
    d.moments.set(m.id, { status: null, level: null, explanation: null, ...m, trace: (m as Partial<Moment>).trace ?? [] })
  }
  for (const o of overlays) {
    if (!d.overlays.has(o.id)) {
      d.overlays.set(o.id, o)
      changed = true
    }
  }
  const have = new Set(d.snapshots.map((s) => s.id))
  for (const s of snapshots) {
    if (!have.has(s.id)) {
      d.snapshots.push(s)
      changed = true
    }
  }
  if (analytics) {
    d.analytics = analytics
    changed = true
  }
  for (const r of recaps) {
    if (!d.recaps.some((x) => x.kind === r.kind && x.cohort === r.cohort)) {
      d.recaps.push(r)
      changed = true
    }
  }
  d.cursors = { event: f.eventCursor, since: f.overlayCursor, msince: f.momentCursor, snap: f.snapshotCursor, av: f.analyticsVersion, rv: f.recapCursor }
  d.summary = rest
  d.receivedAt = now
  if (changed) d.version++
  return d
}

const byTime = (a: Overlay, b: Overlay) => a.displayAt.matchMs - b.displayAt.matchMs || a.priority - b.priority

/** The match sheet the Brain serves, as a ``Meta`` (the final score is not known yet). Make it once per match: the pitch restarts when it changes. */
export const liveMeta = (m: Meta): Meta => ({ ...m, score: {}, scenario: null })

/** The data as a ``Replay`` for the match center: only what has arrived; analytics and recaps come later in the match. */
export function toReplay(id: string, meta: Meta, d: StreamData, tracking: TrackingSource): Replay {
  const events = d.events as MatchEvent[]
  return {
    id,
    meta,
    moments: [...d.moments.values()].sort((a, b) => a.detectedAt.matchMs - b.detectedAt.matchMs),
    overlays: [...d.overlays.values()].sort(byTime),
    snapshots: [...d.snapshots].sort((a, b) => a.matchMs - b.matchMs),
    recaps: d.recaps,
    events,
    eventsById: new Map(events.map((e) => [e.id, e])),
    tracking,
    analytics: d.analytics,
  }
}

// ----- the clock ----------------------------------------------------------------------------------------------

/** Where the feed stands now, in match ms: the server's reading advanced by the wall time since it was taken. */
export function feedEdgeMs(s: Pick<StreamSummary, 'status' | 'clockMs' | 'speed' | 'durationMs' | 'fromMs'>, receivedAt: number, now: number): number {
  if (s.status === 'finished') return s.durationMs
  if (s.status !== 'live') return s.fromMs
  return Math.min(s.durationMs || Infinity, s.clockMs + Math.max(0, now - receivedAt) * s.speed)
}

/** Where the picture is: the feed's edge less the broadcast delay (given in wall seconds, so it is ``delayS * speed`` of match time). Never before kick-off. */
export function playheadMs(edge: number, speed: number, delayS = LIVE_DELAY_S): number {
  return Math.max(0, edge - delayS * speed * 1000)
}

/**
 * The tracking chunks to ask for now: those the pitch is about to need, nearest the playhead first. A chunk is published when the match reaches its end, so
 * none beyond the feed's edge exists yet. The playhead's own chunk matters most: without it the pitch holds the last frame it has, and the players freeze and
 * then leap when it arrives. (Asking in order from far behind the playhead, as a viewer who starts mid-match has chunks for the whole past, never gets there.)
 */
export function chunksDue(playheadMs: number, edgeMs: number, ahead: number, held: (i: number) => boolean, chunkMs = 5000, max = 6): number[] {
  const first = Math.max(0, Math.floor(playheadMs / chunkMs) - 1)
  const last = Math.floor(Math.min(edgeMs, playheadMs + ahead) / chunkMs) - 1
  const out: number[] = []
  for (let i = first; i <= last && out.length < max; i++) if (!held(i)) out.push(i)
  return out
}

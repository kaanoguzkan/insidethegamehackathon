import { describe, expect, it } from 'vitest'
import { chunksDue, emptyStream, feedEdgeMs, LIVE_DELAY_S, liveMeta, mergeFeed, playheadMs, toReplay, type StreamFeed, type StreamOverlay } from './stream'
import type { Meta, Moment } from './types'

const feed = (over: Partial<StreamFeed> = {}): StreamFeed =>
  ({
    matchId: 'red-card-drama', status: 'live', speed: 10, fromMs: 0, wallStartMs: 1000, durationMs: 5_800_000, clockMs: 60_000, serverNowMs: 7000,
    events: [], eventCursor: -1, more: false, overlays: [], overlayCursor: 0, moments: [], momentCursor: 0, snapshots: [], snapshotCursor: 0, analyticsVersion: 0, recaps: [], recapCursor: 0, ...over,
  }) as StreamFeed

const ev = (n: number) => ({ n, arrivalMs: n * 1000, id: `e${n}`, type: 'pass', clock: { period: 1, minute: 0, second: n, matchMs: n * 1000 } })
const ov = (id: string, at: number) => ({ id, displayAt: { matchMs: at }, priority: 1, emittedMs: 0 }) as unknown as StreamOverlay
const mo = (id: string, at: number): Moment => ({ id, detectedAt: { matchMs: at } }) as unknown as Moment

describe('merging the feed', () => {
  it('keeps what arrives once, whatever the order and however often a page is asked for', () => {
    const d = emptyStream()
    mergeFeed(d, feed({ events: [ev(0), ev(1)], eventCursor: 1, overlays: [ov('a', 5)], overlayCursor: 7, moments: [mo('m1', 9)], momentCursor: 3 }), 100)
    const v = d.version
    mergeFeed(d, feed({ events: [ev(1)], eventCursor: 1, overlays: [ov('a', 5)], overlayCursor: 7 }), 200) // the same page again
    expect(d.events.map((e) => e.n)).toEqual([0, 1])
    expect(d.overlays.size).toBe(1)
    expect(d.version).toBe(v)
    mergeFeed(d, feed({ events: [ev(2)], eventCursor: 2, overlays: [ov('b', 3)] }), 300)
    expect(d.version).toBeGreaterThan(v)
    expect(d.cursors).toMatchObject({ event: 2, msince: 0 })
  })

  it('gives a moment the fields the evidence drawer expects and presents it all as a replay sorted by time', () => {
    const d = emptyStream()
    mergeFeed(d, feed({ moments: [mo('m2', 90), mo('m1', 10)], overlays: [ov('x', 50), ov('y', 20)] }), 1)
    const meta = { matchId: 'red-card-drama', home: { id: 'RED' }, away: { id: 'SAL' }, periods: [], hz: 5, frames: 1 } as unknown as Meta
    const r = toReplay('s-1', meta, d, { frames: 0, hz: 5, idsAt: () => [], at: () => ({}) as never })
    expect(r.moments.map((m) => m.id)).toEqual(['m1', 'm2'])
    expect(r.moments[0].trace).toEqual([])
    expect(r.overlays.map((o) => o.id)).toEqual(['y', 'x'])
    expect(r.analytics).toBeNull()
    expect(r.recaps).toEqual([])
    expect(r.meta).toBe(meta) // the same object every rebuild: the pitch restarts when it changes
    expect(liveMeta({ ...meta, score: { RED: 3 } } as unknown as Meta).score).toEqual({})
  })
})

describe('the clock', () => {
  const s = { status: 'live' as const, clockMs: 60_000, speed: 10, durationMs: 5_800_000, fromMs: 0 }
  it('runs on from the server reading at the match speed and stops at the end', () => {
    expect(feedEdgeMs(s, 1000, 1000)).toBe(60_000)
    expect(feedEdgeMs(s, 1000, 3000)).toBe(80_000)
    expect(feedEdgeMs({ ...s, status: 'finished' }, 0, 99)).toBe(5_800_000)
    expect(feedEdgeMs({ ...s, clockMs: 5_799_000 }, 0, 60_000)).toBe(5_800_000)
  })
  it('puts the picture the broadcast delay behind the feed, in wall seconds', () => {
    expect(playheadMs(300_000, 10)).toBe(300_000 - LIVE_DELAY_S * 10_000)
    expect(playheadMs(300_000, 1)).toBe(300_000 - LIVE_DELAY_S * 1000)
    expect(playheadMs(1000, 10)).toBe(0)
  })
  it('asks for the chunks the pitch needs next, starting at the playhead and not in the far past', () => {
    // a viewer who starts at minute 44: the whole past exists, but the pitch needs chunk 527 first
    const first = chunksDue(2_640_000, 2_700_000, 30_000, () => false)
    expect(first[0]).toBe(527)
    expect(first).toHaveLength(6)
    expect(chunksDue(20_000, 60_000, 30_000, () => false)).toEqual([3, 4, 5, 6, 7, 8])
    expect(chunksDue(20_000, 60_000, 30_000, (i) => i < 6)).toEqual([6, 7, 8, 9])
  })
  it('never asks for a chunk the feed has not reached, since it is published when the match gets to its end', () => {
    expect(chunksDue(20_000, 22_000, 30_000, () => false)).toEqual([3])
    expect(chunksDue(0, 4_000, 30_000, () => false)).toEqual([])
  })
})

describe('analytics and recaps', () => {
  it('replace the analytics when a newer one arrives and keep each recap once', () => {
    const d = emptyStream()
    const recap = { kind: 'preview', cohort: 'casual/en/neutral/-', headline: 'h' } as never
    mergeFeed(d, feed({ analytics: { version: 1 } as never, analyticsVersion: 1, recaps: [recap], recapCursor: 1 }), 1)
    mergeFeed(d, feed({ analyticsVersion: 1, recaps: [recap], recapCursor: 1 }), 2) // nothing new: no analytics in the page
    expect(d.analytics).toEqual({ version: 1 })
    expect(d.recaps).toHaveLength(1)
    expect(d.cursors).toMatchObject({ av: 1, rv: 1 })
    mergeFeed(d, feed({ analytics: { version: 2 } as never, analyticsVersion: 2 }), 3)
    expect(d.analytics).toEqual({ version: 2 })
  })
})

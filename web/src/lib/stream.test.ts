import { describe, expect, it } from 'vitest'
import { chunksDue, emptyStream, feedEdgeMs, LIVE_DELAY_S, mergeFeed, playheadMs, toReplay, type StreamFeed } from './stream'
import type { Meta, Moment, Overlay } from './types'

const feed = (over: Partial<StreamFeed> = {}): StreamFeed =>
  ({
    matchId: 'red-card-drama', status: 'live', speed: 10, fromMs: 0, wallStartMs: 1000, durationMs: 5_800_000, clockMs: 60_000, serverNowMs: 7000,
    events: [], eventCursor: -1, more: false, overlays: [], overlayCursor: 0, moments: [], momentCursor: 0, snapshots: [], snapshotCursor: 0, ...over,
  }) as StreamFeed

const ev = (n: number) => ({ n, arrivalMs: n * 1000, id: `e${n}`, type: 'pass', clock: { period: 1, minute: 0, second: n, matchMs: n * 1000 } })
const ov = (id: string, at: number): Overlay => ({ id, displayAt: { matchMs: at }, priority: 1 }) as unknown as Overlay
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
    expect(r.meta.score).toEqual({})
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
  it('asks for the chunks that exist and are not held yet, a few at a time', () => {
    expect(chunksDue(20_000, () => false)).toEqual([0, 1, 2, 3])
    expect(chunksDue(20_000, (i) => i < 2)).toEqual([2, 3])
    expect(chunksDue(4_000, () => false)).toEqual([])
    expect(chunksDue(500_000, () => false, 5000, 2)).toHaveLength(2)
  })
})

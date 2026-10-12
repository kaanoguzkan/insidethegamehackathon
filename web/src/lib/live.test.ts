import { describe, expect, it, vi } from 'vitest'
import { dueOverlays } from '../components/LivePage'
import { clockLabel, getFeed, LiveBusy, liveClock, type LiveEvent, type LiveMoment, type LiveOverlay, median, pipelineDelays, scoreOf, startLive, writer } from './live'
import type { Overlay } from './types'

const ov = (id: string, over: Partial<LiveOverlay> = {}): LiveOverlay =>
  ({
    id, matchId: 'm', momentId: null, kind: 'lower_third', displayAt: { matchMs: 1000 }, durationMs: 8000, priority: 5,
    cohort: { mode: 'casual', language: 'en', perspective: 'neutral', focusPlayer: null },
    content: { headline: 'H', body: 'B', chips: [] }, anchor: { type: 'screen' },
    provenance: { agents: ['composer'], verified: true, fallbackLevel: 0 }, schemaVersion: '1', emittedMs: 0, ...over,
  }) as LiveOverlay

describe('the live clock', () => {
  const live = { status: 'live' as const, clockMs: 600_000, speed: 5, durationMs: 5_700_000, fromMs: 600_000 }
  it('runs on between polls at the match speed', () => {
    expect(liveClock(live, 1000, 1000)).toBe(600_000)
    expect(liveClock(live, 1000, 11_000)).toBe(650_000)
  })
  it('never runs backwards, past the end, or while the match has not started', () => {
    expect(liveClock(live, 5000, 1000)).toBe(600_000)
    expect(liveClock(live, 0, 10 ** 9)).toBe(5_700_000)
    expect(liveClock({ ...live, status: 'scheduled' }, 0, 10 ** 9)).toBe(600_000)
    expect(liveClock({ ...live, status: 'finished' }, 0, 10 ** 9)).toBe(5_700_000)
  })
  it('formats minutes and seconds', () => {
    expect(clockLabel(0)).toBe('0:00')
    expect(clockLabel(3_605_000)).toBe('60:05')
    expect(clockLabel(-5)).toBe('0:00')
  })
})

describe('the score', () => {
  const g = (n: number, team: string): LiveEvent => ({ n, arrivalMs: 0, id: String(n), type: 'goal', clock: { period: 1, minute: 1, second: 0, matchMs: 0 }, team })
  it('counts goals per club and ignores other events', () => {
    const shot = { ...g(9, 'RED'), type: 'shot' }
    expect(scoreOf([g(1, 'RED'), g(2, 'SAL'), g(3, 'SAL'), shot], 'RED', 'SAL')).toEqual([1, 2])
    expect(scoreOf([], 'RED', 'SAL')).toEqual([0, 0])
  })
})

describe('the pipeline delay', () => {
  const match = { wallStartMs: 1_000_000, speed: 5, fromMs: 600_000 }
  const mo = (id: string, ms: number): LiveMoment => ({ id, type: 'goal', salience: 1, detectedAt: { matchMs: ms } })
  it('is the wall time from when the moment happened to when its story was stored', () => {
    // a moment 100 match seconds after the start is 20 wall seconds in at 5x
    const out = pipelineDelays(match, [mo('a', 700_000)], [ov('o', { momentId: 'a', emittedMs: 1_000_000 + 20_000 + 7_500 })])
    expect(out).toEqual([7.5])
  })
  it('uses the first story of a moment, skips the past and moments without a story, and never goes negative', () => {
    const early = ov('o1', { momentId: 'a', emittedMs: 1_030_000 })
    const late = ov('o2', { momentId: 'a', emittedMs: 1_060_000 })
    const tick = ov('o3', { momentId: 'a', kind: 'ticker', emittedMs: 1_001_000 })
    expect(pipelineDelays(match, [mo('a', 700_000), mo('old', 500_000), mo('none', 800_000)], [late, early, tick, ov('o4', { momentId: 'old', emittedMs: 1_050_000 })])).toEqual([10])
    expect(pipelineDelays(match, [mo('a', 700_000)], [ov('o', { momentId: 'a', emittedMs: 1_000_000 })])).toEqual([0])
    expect(pipelineDelays({ wallStartMs: null, speed: 5, fromMs: 0 }, [mo('a', 1)], [])).toEqual([])
  })
  it('has a median', () => {
    expect(median([])).toBeNull()
    expect(median([3, 1, 2])).toBe(2)
    expect(median([1, 2, 3, 4])).toBe(2.5)
  })
})

describe('what is on screen', () => {
  it('shows this viewer type, once its time has come, newest first', () => {
    const rows = [
      ov('now', { displayAt: { matchMs: 5000 } }),
      ov('older', { displayAt: { matchMs: 2000 } }),
      ov('future', { displayAt: { matchMs: 9000 } }),
      ov('es', { displayAt: { matchMs: 1000 }, cohort: { mode: 'casual', language: 'es', perspective: 'neutral', focusPlayer: null } }),
      ov('analyst', { displayAt: { matchMs: 1000 }, cohort: { mode: 'analyst', language: 'en', perspective: 'neutral', focusPlayer: null } }),
      ov('fan', { displayAt: { matchMs: 1000 }, cohort: { mode: 'casual', language: 'en', perspective: 'RED', focusPlayer: null } }),
      ov('shared', { displayAt: { matchMs: 3000 }, kind: 'fact_card', cohort: { mode: 'any', language: 'en', perspective: 'neutral', focusPlayer: null } }),
      ov('graphic', { displayAt: { matchMs: 1000 }, kind: 'graphic' }),
    ]
    expect(dueOverlays(rows, 'en', 'casual', 6000).map((o) => o.id)).toEqual(['now', 'shared', 'older'])
  })
})

describe('who wrote an overlay', () => {
  const o = (level: number) => ({ provenance: { agents: [], verified: true, fallbackLevel: level } }) as unknown as Overlay
  it('reads the fallback level', () => {
    expect([writer(o(0)), writer(o(1)), writer(o(2))]).toEqual(['model', 'mended', 'template'])
  })
})

describe('talking to the Brain', () => {
  it('turns a running match into a LiveBusy that carries its id', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: { detail: 'running', matchId: 'live-x' } }), { status: 409 })))
    await expect(startLive('red-card-drama', 0, 'https://brain.test')).rejects.toBeInstanceOf(LiveBusy)
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 429 })))
    await expect(startLive('red-card-drama', 0, 'https://brain.test')).rejects.toThrow('rate')
    vi.unstubAllGlobals()
  })
  it('refuses an id that is not a slug before any request', async () => {
    const f = vi.fn()
    vi.stubGlobal('fetch', f)
    await expect(getFeed('../x', -1, 0, 'https://brain.test')).rejects.toThrow('invalid id')
    expect(f).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
})

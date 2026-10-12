import { describe, expect, it, vi } from 'vitest'
import { dueOverlays } from '../components/LivePage'
import { clockLabel, getFeed, LiveBusy, liveClock, type LiveEvent, type LiveMoment, type LiveOverlay, median, pipelineDelays, playClock, scoreOf, stageDelays, startLive, writer } from './live'
import { type ChunkJson, LiveTracking } from './tracking'
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

describe('live tracking', () => {
  // five frames at 5 Hz per chunk keeps the arithmetic readable; the real feed has 25 per chunk
  const chunk = (index: number, n: number, x0: number, off: number[] = []): ChunkJson => ({
    matchId: 'm', chunk: index, startMs: index * n * 200, hz: 5, scale: 10, slots: Array.from({ length: 22 }, (_, i) => `P${index}-${i}`),
    ball: Array.from({ length: n }, (_, k) => [x0 + k * 10, 340, 0]), alive: Array.from({ length: n }, () => 1),
    players: Array.from({ length: n }, (_, k) => Array.from({ length: 22 }, (_, j) => (off.includes(j) ? null : [x0 + k * 10, 100 + j * 10]))),
  })

  it('answers like the recorded tracking: positions in metres, interpolated between frames', () => {
    const tr = new LiveTracking()
    tr.addChunk(chunk(0, 25, 100)) // x = 10.0 m at frame 0, 11.0 m at frame 1 ...
    expect(tr.frames).toBe(25)
    const f = tr.at(0)
    expect(f.players).toHaveLength(22)
    expect(f.players[0]).toMatchObject({ slot: 0, id: 'P0-0', x: 10, y: 10 })
    expect(tr.at(100).players[0].x).toBeCloseTo(10.5, 5) // half a frame (at 5 Hz a frame is 200 ms)
    expect(tr.at(200).players[0].x).toBeCloseTo(11, 5)
    expect(f.ball).toMatchObject({ x: 10, y: 34, alive: true })
  })

  it('leaves out a player who is off the pitch and does not interpolate across a dead ball', () => {
    const tr = new LiveTracking()
    const c = chunk(0, 5, 100, [3])
    c.alive[1] = 0
    tr.addChunk(c)
    expect(tr.at(0).players.map((p) => p.slot)).not.toContain(3)
    expect(tr.at(0).players).toHaveLength(21)
    expect(tr.at(100).ball.x).toBe(10) // the ball is carried, not flown, from a dead frame
  })

  it('interpolates across a chunk boundary and takes the substitution table of the chunk it is in', () => {
    const tr = new LiveTracking()
    tr.addChunk(chunk(0, 5, 100))
    tr.addChunk(chunk(1, 5, 150))
    expect(tr.at(900).players[0].x).toBeCloseTo(14.5, 5) // frame 4.5: halfway between the last frame of chunk 0 (14 m) and the first of chunk 1 (15 m)
    expect(tr.idsAt(5)[0]).toBe('P1-0')
    expect(tr.idsAt(4)[0]).toBe('P0-0')
  })

  it('holds the nearest frame it has where a chunk has not arrived, and says what it has', () => {
    const tr = new LiveTracking()
    expect(tr.at(1000).players).toEqual([]) // nothing yet: an empty pitch, not an error
    tr.addChunk(chunk(2, 5, 200))
    expect(tr.last).toBe(2)
    expect(tr.has(0)).toBe(false)
    expect(tr.at(0).players[0].x).toBe(20) // before the first chunk it has: its first frame
    tr.addChunk(chunk(0, 5, 100))
    expect(tr.at(1400).players[0].x).toBeCloseTo(14.0, 5) // frame 7 is in chunk 1, which is missing: the last frame of chunk 0 is held
    expect(tr.frames).toBe(15)
  })
})

describe('where the delay goes', () => {
  const match = { wallStartMs: 1_000_000, speed: 5, fromMs: 600_000 }
  it('splits the time into detecting a moment and writing its overlay', () => {
    const mo = (id: string, ms: number, createdMs: number | null): LiveMoment => ({ id, type: 'goal', salience: 1, detectedAt: { matchMs: ms }, createdMs })
    const a = mo('a', 700_000, 1_000_000 + 20_000 + 4_000) // detectable 20 s in; stored 4 s later
    const old = mo('old', 700_000, null) // an older run: no creation time
    const early = mo('early', 500_000, 1_000_000) // before the run began
    const out = stageDelays(
      match,
      [a, old, early],
      [ov('o1', { momentId: 'a', emittedMs: 1_000_000 + 20_000 + 4_000 + 6_500 }), ov('o2', { momentId: 'old', emittedMs: 1_050_000 }), ov('o3', { momentId: 'early', emittedMs: 1_001_000 })],
    )
    expect(out.interpret).toEqual([4]) // seconds
    expect(out.write).toEqual([6.5])
    expect(stageDelays({ wallStartMs: null, speed: 5, fromMs: 0 }, [a], [])).toEqual({ interpret: [], write: [] })
  })
})

describe('the playing clock', () => {
  it('runs the given wall seconds behind the live feed, in match time, and never before the start', () => {
    expect(playClock(3_000_000, 5, 25)).toBe(3_000_000 - 125_000)
    expect(playClock(60_000, 5, 25)).toBe(0)
    expect(playClock(3_000_000, null, 25)).toBe(3_000_000 - 25_000)
  })
})

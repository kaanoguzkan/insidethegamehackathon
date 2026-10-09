import { afterEach, describe, expect, it, vi } from 'vitest'
import { cohortKey, mergeLive, prewarm, requestBeats, wakeBrain, type LiveResult } from './brain'
import { cohortForMatch } from './cohort'
import { DEFAULT_PROFILE, type Cohort, type Meta, type Overlay } from './types'

const cohort = (over: Partial<Cohort> = {}): Cohort => ({ mode: 'casual', language: 'en', perspective: 'neutral', focusPlayer: null, ...over })
const overlay = (id: string, level: number, over: Partial<Overlay> = {}): Overlay => ({
  id, matchId: 'm', momentId: 'mo-1', kind: 'lower_third', displayAt: { matchMs: 1000 }, durationMs: 9000, priority: 2,
  cohort: cohort(), content: { headline: id, body: '', chips: [] }, anchor: { type: 'screen' },
  provenance: { agents: [], verified: true, fallbackLevel: level }, schemaVersion: '1.0', ...over,
})
const result = (overlays: Overlay[]): LiveResult => ({ momentId: 'mo-1', overlays, elapsedMs: 2500, stats: null })

afterEach(() => vi.unstubAllGlobals())

describe('cohortKey', () => {
  it('matches the Python key', () => {
    expect(cohortKey(cohort())).toBe('casual/en/neutral/-')
    expect(cohortKey(cohort({ mode: 'analyst', language: 'tr', perspective: 'NOR', focusPlayer: 'NOR-9' }))).toBe('analyst/tr/NOR/NOR-9')
  })
})

describe('mergeLive', () => {
  it('replaces the recorded lower third for the same moment and cohort with model text', () => {
    const rec = overlay('recorded', 2)
    const other = overlay('other-cohort', 0, { cohort: cohort({ language: 'es' }) })
    const merged = mergeLive([rec, other], [result([overlay('live', 0)])])
    expect(merged.map((o) => o.id)).toEqual(['other-cohort', 'live'])
    expect(merged.find((o) => o.id === 'recorded')).toBeUndefined()
  })
  it('keeps recorded text when the live answer is only a template', () => {
    const rec = overlay('recorded', 0)
    expect(mergeLive([rec], [result([overlay('live-template', 2)])])).toEqual([rec])
  })
  it('keeps other overlay kinds and orders by time', () => {
    const ticker = overlay('tk', 0, { kind: 'ticker', displayAt: { matchMs: 500 } })
    const merged = mergeLive([ticker, overlay('recorded', 2)], [result([overlay('live', 1)])])
    expect(merged.map((o) => o.id)).toEqual(['tk', 'live'])
  })
  it('returns the input untouched with no results', () => {
    const base = [overlay('a', 0)]
    expect(mergeLive(base, [])).toBe(base)
  })
})

describe('Brain requests', () => {
  it('posts one moment with the viewer cohorts in fast mode and flattens the overlays', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ elapsedMs: 2700, stats: { cacheHits: 1, modelCalls: 0, repaired: 0, rejected: 0, missedDeadline: 0 }, beats: [{ overlays: [overlay('a', 0)] }, { overlays: [overlay('b', 1)] }] }) })
    vi.stubGlobal('fetch', fetchMock)
    const r = await requestBeats('mo-1', 'red-card-drama', [cohort()], 'https://brain.test')
    expect(r.overlays.map((o) => o.id)).toEqual(['a', 'b'])
    expect(r.elapsedMs).toBe(2700)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('https://brain.test/api/beats')
    expect(JSON.parse(init.body)).toMatchObject({ match_id: 'red-card-drama', moment_ids: ['mo-1'], mode: 'fast', deadlineMs: 5000 })
  })
  it('refuses ids that are not plain slugs before any request', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await expect(requestBeats('../x', 'm', [cohort()], 'https://brain.test')).rejects.toThrow('invalid id')
    expect(fetchMock).not.toHaveBeenCalled()
  })
  it('reports a failed answer as an error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }))
    await expect(requestBeats('mo-1', 'm', [cohort()], 'https://brain.test')).rejects.toThrow('503')
  })
  it('wakeBrain is true when the health check answers and false when it does not', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }))
    expect(await wakeBrain('https://brain.test')).toBe(true)
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network')))
    expect(await wakeBrain('https://brain.test')).toBe(false)
  })
  it('prewarm never throws and does nothing without an address', () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('network'))
    vi.stubGlobal('fetch', fetchMock)
    prewarm('')
    expect(fetchMock).not.toHaveBeenCalled()
    expect(() => prewarm('https://brain.test')).not.toThrow()
  })
})

describe('cohortForMatch', () => {
  const team = (id: string, players: string[]) => ({ id, players: Object.fromEntries(players.map((p) => [p, { name: p, pos: 'CM', number: 1 }])) })
  const meta = { home: team('RED', ['RED-01', 'RED-09']), away: team('SAL', ['SAL-01']) } as unknown as Meta
  it('keeps a club and a player that belong to the match', () => {
    const c = cohortForMatch({ ...DEFAULT_PROFILE, perspective: 'RED', focusPlayer: 'SAL-01', mode: 'analyst', language: 'tr' }, meta)
    expect(c).toEqual({ mode: 'analyst', language: 'tr', perspective: 'RED', focusPlayer: 'SAL-01' })
  })
  it('drops a club and a player from another match, which the Brain would refuse', () => {
    const c = cohortForMatch({ ...DEFAULT_PROFILE, perspective: 'KES', focusPlayer: 'KES-07' }, meta)
    expect(c.perspective).toBe('neutral')
    expect(c.focusPlayer).toBeNull()
  })
})

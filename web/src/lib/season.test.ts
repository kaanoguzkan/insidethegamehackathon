import { afterEach, describe, expect, it, vi } from 'vitest'
import { parseHash } from '../hooks/useHash'
import { fixtureLabel, SeasonBusy, SeasonWait, simulateSeason, tune } from './season'

afterEach(() => vi.unstubAllGlobals())

describe('the routes', () => {
  it('opens the live channel by default and the replay match center at /replay', () => {
    expect(parseHash('').view).toBe('home')
    expect(parseHash('#/').view).toBe('home')
    expect(parseHash('#/?mode=analyst&lang=es').view).toBe('home')
    expect(parseHash('#/replay?match=red-card-drama').view).toBe('center')
    expect(parseHash('#/season').view).toBe('season')
    expect(parseHash('#/broadcast?match=red-card-drama').view).toBe('broadcast')
  })
  it('still opens a replay for the links made before the channel became the home page, but a live match id stays on the home page', () => {
    expect(parseHash('#/?match=pressing-collapse&t=60').view).toBe('center')
    expect(parseHash('#/?match=live-season-1-f01-120000').view).toBe('home')
    expect(parseHash('#/?match=live-season-1-f01-120000').match).toBe('live-season-1-f01-120000')
  })
})

describe('talking to the season endpoints', () => {
  it('turns "not simulated yet" into SeasonWait and a rate limit into an error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 503 })))
    await expect(tune({}, 'https://brain.test')).rejects.toBeInstanceOf(SeasonWait)
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 429 })))
    await expect(tune({}, 'https://brain.test')).rejects.toThrow('rate')
  })
  it('sends what was asked for', async () => {
    const f = vi.fn(async () => new Response(JSON.stringify({ matchId: 'live-x', seasonId: 's', fixtureId: 'f02', round: 1, speed: 5, heartbeatMs: 1 }), { status: 200 }))
    vi.stubGlobal('fetch', f)
    expect((await tune({ fixtureId: 'f02', speed: 10 }, 'https://brain.test')).matchId).toBe('live-x')
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('https://brain.test/api/channel/tune')
    expect(JSON.parse(init.body as string)).toEqual({ fixtureId: 'f02', speed: 10 })
  })
  it('follows a season that is already being simulated', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: { detail: 'busy', seasonId: 'season-7' } }), { status: 409 })))
    await expect(simulateSeason('https://brain.test')).rejects.toBeInstanceOf(SeasonBusy)
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ seasonId: 'season-8' }), { status: 200 })))
    expect((await simulateSeason('https://brain.test')).seasonId).toBe('season-8')
  })
  it('labels a fixture with the clubs short names', () => {
    const clubs = { RED: { name: 'Redmoor United', short: 'Redmoor', primary: '#7A1F2B', secondary: '#E8D9B0' } }
    expect(fixtureLabel({ round: 1, home: 'RED', away: 'XXX' }, clubs)).toBe('Redmoor v XXX')
  })
})

import { readFileSync } from 'node:fs'
import { gunzipSync } from 'node:zlib'
import { describe, expect, it } from 'vitest'
import { buildHash, parseHash } from '../hooks/useHash'
import { clockAt, totalMs } from './clock'
import { phaseAt, winProbAt, type Analytics } from './analytics'
import { covers } from './cohort'
import { homeControl, homeShare, NX, NY } from './control'
import { convexHull, defensiveLine, laneBlock, offsideLineX, passingLanes, polygonArea } from './geometry'
import { attackDir, fade } from './layers'
import { activeAt, isShown, visibleOverlays } from './overlays'
import { isNarrative, overlaysFor, SAFE_ID, type Replay } from './data'
import { recapFor, recapReady } from './recap'
import { formationAt, setPieceCounts, tagKeys, totalCorners } from './tactics'
import { maybeGunzip, Tracking, type Frame } from './tracking'
import { DEFAULT_PROFILE, type Cohort, type MatchEvent, type Meta, type Overlay, type Profile } from './types'

const dir = new URL('../../../data/replays/pressing-collapse/', import.meta.url)
const read = (f: string) => readFileSync(new URL(f, dir))
const meta = JSON.parse(read('meta.json').toString()) as Meta
const overlays = JSON.parse(read('overlays.json').toString()) as Overlay[]

function tracking(): Tracking {
  const raw = gunzipSync(read('tracking.bin.gz'))
  const ab = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength) as ArrayBuffer
  return new Tracking(ab, JSON.parse(read('slots.json').toString()))
}

describe('tracking bundle', () => {
  const t = tracking()
  it('decodes the header and matches the package metadata', () => {
    expect(t.frames).toBe(meta.frames)
    expect(t.hz).toBe(5)
  })
  it('returns 22 players on the pitch at kick-off, inside the pitch', () => {
    const f = t.at(10_000)
    expect(f.players).toHaveLength(22)
    for (const p of f.players) {
      expect(p.x).toBeGreaterThan(-2)
      expect(p.x).toBeLessThan(107)
      expect(p.y).toBeGreaterThan(-2)
      expect(p.y).toBeLessThan(70)
      expect(p.id).toMatch(/^[A-Z]{3}-\d{2}$/)
    }
  })
  it('interpolates smoothly between frames', () => {
    const a = t.at(60_000)
    const b = t.at(60_100)
    const c = t.at(60_200)
    const mid = b.players[3]
    expect(mid.x).toBeGreaterThanOrEqual(Math.min(a.players[3].x, c.players[3].x) - 0.01)
    expect(mid.x).toBeLessThanOrEqual(Math.max(a.players[3].x, c.players[3].x) + 0.01)
  })
  it('clamps outside the recording', () => {
    expect(t.at(-5).players.length).toBe(22)
    expect(t.at(1e12).ball).toBeDefined()
  })
  it('shows substitutions as a change of player id in a slot', () => {
    const early = t.idsAt(0)
    const late = t.idsAt(t.frames - 1)
    expect(early.filter((id, i) => id !== late[i]).length).toBeGreaterThan(0)
  })
  it('rejects data that is not a bundle', () => {
    expect(() => new Tracking(new ArrayBuffer(32), [])).toThrow()
  })
})

describe('clock', () => {
  it('restarts the second half at 45:00', () => {
    const p2 = meta.periods[1].startMs
    expect(clockAt(meta, 61_000).label).toBe('01:01')
    expect(clockAt(meta, p2 + 5_000).label).toBe('45:05')
    expect(clockAt(meta, p2 + 15 * 60_000).minute).toBe(60)
  })
  it('knows how long the recording is', () => {
    expect(totalMs(meta)).toBeGreaterThan(90 * 60_000)
  })
})

describe('cohort matching mirrors the Python contract', () => {
  const viewer: Cohort = { mode: 'casual', language: 'es', perspective: 'HAR', focusPlayer: null }
  it('shared stat graphics match every mode that reads the language', () => {
    expect(covers({ mode: 'any', language: 'es', perspective: 'neutral', focusPlayer: null }, viewer)).toBe(true)
    expect(covers({ mode: 'any', language: 'en', perspective: 'neutral', focusPlayer: null }, viewer)).toBe(false)
  })
  it('narrative overlays need the same mode and a compatible perspective', () => {
    expect(covers({ mode: 'casual', language: 'es', perspective: 'HAR', focusPlayer: null }, viewer)).toBe(true)
    expect(covers({ mode: 'casual', language: 'es', perspective: 'NOR', focusPlayer: null }, viewer)).toBe(false)
    expect(covers({ mode: 'analyst', language: 'es', perspective: 'neutral', focusPlayer: null }, viewer)).toBe(false)
  })
})

describe('overlay selection', () => {
  const p: Profile = { ...DEFAULT_PROFILE, language: 'en', mode: 'analyst' }
  const viewer: Cohort = { mode: 'analyst', language: 'en', perspective: 'neutral', focusPlayer: null }
  const lt = overlays.find((o) => o.kind === 'lower_third' && o.cohort.mode === 'analyst' && o.cohort.language === 'en' && o.priority <= 3)!
  it('activates an overlay only inside its display window', () => {
    const t = lt.displayAt.matchMs
    expect(activeAt(overlays, t - 1).includes(lt)).toBe(false)
    expect(activeAt(overlays, t).includes(lt)).toBe(true)
    expect(activeAt(overlays, t + lt.durationMs).includes(lt)).toBe(false)
  })
  it('personalizes: an analyst and a casual Spanish viewer see different text for the same moment', () => {
    const t = lt.displayAt.matchMs + 100
    const a = visibleOverlays(overlays, t, p, viewer).filter((o) => o.momentId === lt.momentId)
    const es: Profile = { ...p, mode: 'casual', language: 'es' }
    const b = visibleOverlays(overlays, t, es, { mode: 'casual', language: 'es', perspective: 'neutral', focusPlayer: null }).filter((o) => o.momentId === lt.momentId)
    expect(a.length).toBe(1)
    expect(b.length).toBe(1)
    expect(a[0].content.body).not.toBe(b[0].content.body)
  })
  it('density filters low-priority graphics', () => {
    const badge = overlays.find((o) => o.kind === 'speed_badge')!
    const low: Profile = { ...p, density: 'low' }
    const high: Profile = { ...p, density: 'high' }
    expect(isShown(badge, low, viewer)).toBe(false)
    expect(isShown(badge, high, viewer)).toBe(true)
  })
  it('never shows an overlay written for another language', () => {
    const t = lt.displayAt.matchMs + 100
    expect(visibleOverlays(overlays, t, p, viewer).every((o) => o.cohort.language === 'en')).toBe(true)
  })
})

describe('gzip handling across hosts', () => {
  const gz = read('tracking.bin.gz')
  const ab = gz.buffer.slice(gz.byteOffset, gz.byteOffset + gz.byteLength) as ArrayBuffer
  it('decompresses raw gzip (hosts that do not set Content-Encoding)', async () => {
    const out = await maybeGunzip(ab)
    expect(String.fromCharCode(...new Uint8Array(out, 0, 4))).toBe('MMT1')
  })
  it('passes through bytes the browser already decompressed', async () => {
    const decoded = await maybeGunzip(ab)
    const again = await maybeGunzip(decoded)
    expect(again.byteLength).toBe(decoded.byteLength)
  })
})

describe('replay ids', () => {
  it('accepts slugs and rejects path tricks', () => {
    for (const ok of ['pressing-collapse', 'red-card-drama', 'a1']) expect(SAFE_ID.test(ok)).toBe(true)
    for (const bad of ['../x', 'a/b', '..', '', 'A', 'a b', 'x?y', '%2e%2e']) expect(SAFE_ID.test(bad)).toBe(false)
  })
})

describe('recaps', () => {
  const recaps = JSON.parse(read('recaps.json').toString()) as import('./types').Recap[]
  const p: Profile = { ...DEFAULT_PROFILE, mode: 'casual', language: 'es', perspective: 'neutral' }
  it('has a recap for every kind in the viewer language and mode', () => {
    for (const kind of ['preview', 'half_time', 'full_time'] as const) {
      const r = recapFor(recaps, kind, p)!
      expect(r.cohort).toBe('casual/es/neutral/-')
      expect(r.summary.length).toBeGreaterThan(20)
      expect(r.provenance.verified).toBe(true)
    }
  })
  it('falls back to the neutral cohort when no club-specific recap exists', () => {
    const r = recapFor(recaps, 'full_time', { ...p, perspective: 'HAR' })
    expect(r?.cohort).toBe('casual/es/neutral/-')
  })
  it('only reveals a recap once the match has reached it', () => {
    expect(recapReady('preview', 0, 1000, 5000)).toBe(true)
    expect(recapReady('half_time', 999, 1000, 5000)).toBe(false)
    expect(recapReady('half_time', 1000, 1000, 5000)).toBe(true)
    expect(recapReady('full_time', 4999, 1000, 5000)).toBe(false)
  })
})

describe('model-health variants', () => {
  const fake = { overlays } as unknown as Replay
  const outage = overlays.filter(isNarrative).map((o) => ({ ...o, provenance: { ...o.provenance, fallbackLevel: 2 } }))
  it('healthy uses the package overlays untouched', () => {
    expect(overlaysFor(fake, 'healthy', {})).toBe(overlays)
  })
  it('swaps only the narrative overlays and keeps every shared graphic', () => {
    const merged = overlaysFor(fake, 'outage', { outage })
    expect(merged.filter((o) => !isNarrative(o)).length).toBe(overlays.filter((o) => !isNarrative(o)).length)
    expect(merged.filter(isNarrative).every((o) => o.provenance.fallbackLevel === 2)).toBe(true)
  })
  it('stays sorted by display time', () => {
    const m = overlaysFor(fake, 'outage', { outage })
    for (let i = 1; i < m.length; i++) expect(m[i].displayAt.matchMs).toBeGreaterThanOrEqual(m[i - 1].displayAt.matchMs)
  })
  it('falls back to the healthy set until a variant has loaded', () => {
    expect(overlaysFor(fake, 'unreliable', {})).toBe(overlays)
  })
})

describe('tactics panel data', () => {
  const rc = new URL('../../../data/replays/red-card-drama/', import.meta.url)
  const rcMeta = JSON.parse(readFileSync(new URL('meta.json', rc)).toString()) as Meta
  const rcEvents = JSON.parse(readFileSync(new URL('events.json', rc)).toString()) as MatchEvent[]
  const fake = { events: rcEvents } as unknown as Replay

  it('starts in the nominal formation and switches when the formation_change event arrives', () => {
    const red = rcMeta.home
    expect(formationAt(fake, red, 0)).toMatchObject({ name: '4-4-2', changed: false, block: '4-4-2' })
    const change = rcEvents.find((e) => e.type === 'formation_change' && e.team === red.id)!
    const after = formationAt(fake, red, change.clock.matchMs + 1)
    expect(after).toMatchObject({ name: '4-1-4-1', changed: true })
    expect(after.block).toBe('4-5-1')
    expect(formationAt(fake, red, change.clock.matchMs - 1).name).toBe('4-4-2')
  })

  it('counts set-piece routines up to the current time only', () => {
    const red = rcMeta.home.id
    const end = Number.MAX_SAFE_INTEGER
    const all = setPieceCounts(rcEvents, red, end)
    expect(totalCorners(all)).toBe(rcEvents.filter((e) => e.type === 'corner' && e.team === red).length)
    expect(all.goalKicks.short + all.goalKicks.long).toBe(rcEvents.filter((e) => e.type === 'goal_kick' && e.team === red).length)
    expect(totalCorners(setPieceCounts(rcEvents, red, 0))).toBe(0)
    const half = setPieceCounts(rcEvents, red, 45 * 60_000)
    expect(totalCorners(half)).toBeLessThanOrEqual(totalCorners(all))
  })

  it('names only the tactic tags that depart from the defaults', () => {
    expect(tagKeys(meta.home)).toEqual(expect.arrayContaining(['tag.fullbacks.inverted', 'tag.striker.false9', 'tag.build_up.short', 'tag.corners.short', 'tag.corner_defence.zonal']))
    expect(tagKeys(meta.home)).not.toContain('tag.pivot.stay')
    expect(tagKeys({ ...meta.home, style: { fullbacks: 'hold', pivot: 'stay', corner_defence: 'man', long_throws: true } })).toEqual(['tag.corner_defence.man', 'tag.long_throws'])
  })
})

describe('pitch control parity with Python', () => {
  const fx = JSON.parse(readFileSync(new URL('../../../tests/fixtures/pitch_control.json', import.meta.url)).toString()) as { nx: number; ny: number; frames: { players: [number, number][]; grid: number[] }[] }
  it('matches the fixture the Python implementation is checked against', () => {
    expect([fx.nx, fx.ny]).toEqual([NX, NY])
    for (const f of fx.frames) {
      const got = homeControl(f.players.map(([x, y], slot) => ({ slot, x, y })))
      expect(got.length).toBe(f.grid.length)
      let worst = 0
      f.grid.forEach((v, i) => (worst = Math.max(worst, Math.abs(got[i] - v))))
      expect(worst).toBeLessThan(2e-4)
    }
  })
  it('gives each side the part of the pitch it is nearest to', () => {
    const players = [...Array(11).keys()].map((slot) => ({ slot, x: 15, y: 34 })).concat([...Array(11).keys()].map((i) => ({ slot: 11 + i, x: 90, y: 34 })))
    const g = homeControl(players)
    expect(g[7 * NX + 0]).toBeGreaterThan(0.95)
    expect(g[7 * NX + NX - 1]).toBeLessThan(0.05)
    expect(homeShare(g)).toBeGreaterThan(0.3)
    expect(homeShare(g)).toBeLessThan(0.7)
  })
})

describe('pitch geometry', () => {
  const frame = (pts: [number, number][]): Frame => ({ ball: { x: 0, y: 0, z: 0, alive: true }, players: pts.map(([x, y], slot) => ({ slot, id: `p${slot}`, x, y })) })
  it('takes the convex hull of a team and measures its area', () => {
    const h = convexHull([[0, 0], [10, 0], [10, 10], [0, 10], [5, 5], [3, 4]])
    expect(h).toHaveLength(4)
    expect(polygonArea(h)).toBeCloseTo(100)
  })
  it('puts the offside line on the second-deepest outfield defender', () => {
    // Away team (slots 11-21) attacks toward x = 0; its own goal is at x = 105. Keeper at 104, then 98, 90, ...
    const away: [number, number][] = [[104, 34], [98, 10], [90, 20], [85, 30], [80, 40], [75, 50], [70, 20], [66, 30], [60, 40], [58, 50], [55, 34]]
    const f = frame([...Array(11).fill([40, 34]), ...away] as [number, number][])
    expect(offsideLineX(f, 1, -1)).toBe(90)
  })
  it('reads a back line as the four deepest outfield players, ordered across the pitch', () => {
    const home: [number, number][] = [[3, 34], [20, 50], [21, 20], [22, 40], [23, 28], [40, 10], [41, 60], [45, 30], [55, 34], [60, 20], [62, 50]]
    const f = frame([...home, ...Array(11).fill([80, 34])] as [number, number][])
    const line = defensiveLine(f, 0, 1)
    expect(line.map((p) => p[0]).sort()).toEqual([20, 21, 22, 23])
    expect(line.map((p) => p[1])).toEqual([20, 28, 40, 50])
  })
  it('scores a passing lane as blocked by a defender standing on it and clear when nobody is near', () => {
    const opp = [{ slot: 11, id: 'o', x: 20, y: 34 }]
    expect(laneBlock([10, 34], [30, 34], opp)).toBeGreaterThan(0.9)
    expect(laneBlock([10, 34], [30, 34], [{ slot: 11, id: 'o', x: 20, y: 50 }])).toBe(0)
  })
  it('offers the carrier forward, open options first', () => {
    const f = frame([[30, 34], [45, 20], [45, 50], [20, 34], ...Array(7).fill([10, 5]), ...Array(11).fill([100, 60])] as [number, number][])
    const lanes = passingLanes(f, f.players[0], 1, 2)
    expect(lanes.length).toBe(2)
    expect(lanes.every((l) => l.forward > 0)).toBe(true)
  })
})

describe('analytics data', () => {
  const an = JSON.parse(readFileSync(new URL('analytics.json', dir)).toString()) as Analytics
  it('interpolates win probability between minute ticks and steps at goals', () => {
    const pre = winProbAt(an, 0)!
    expect(pre.home + pre.draw + pre.away).toBeCloseTo(1, 2)
    const goal = an.winProbability.swings.find((s) => s.kind === 'goal')!
    const before = winProbAt(an, goal.matchMs - 2)!
    const after = winProbAt(an, goal.matchMs + 2)!
    expect(Math.abs(after.home - before.home) + Math.abs(after.away - before.away)).toBeGreaterThan(0.02)
    expect(winProbAt(null, 0)).toBeNull()
  })
  it('is the same match as the package metadata', () => {
    expect(an.clubs).toEqual([meta.home.id, meta.away.id])
    expect(an.players.length).toBeGreaterThan(18)
    expect(Object.keys(an.shapes)).toEqual(an.clubs)
    expect(an.season?.standings).toHaveLength(6)
  })
  it('has pitch graphics in the overlays, with geometry inside the pitch', () => {
    const gs = overlays.filter((o) => o.kind === 'pitch_graphic')
    expect(gs.length).toBeGreaterThan(5)
    for (const o of gs) {
      expect(o.graphic?.shapes.length).toBeGreaterThan(0)
      for (const sh of o.graphic!.shapes) for (const p of sh.points) expect(p.x >= -1 && p.x <= 106 && p.y >= -1 && p.y <= 69).toBe(true)
    }
  })
  it('fades graphics in and out', () => {
    const g = overlays.find((o) => o.kind === 'pitch_graphic')!
    expect(fade(g, g.displayAt.matchMs)).toBe(0)
    expect(fade(g, g.displayAt.matchMs + g.durationMs / 2)).toBe(1)
    expect(fade(g, g.displayAt.matchMs + g.durationMs)).toBe(0)
  })
  it('knows which way a club attacks in each half', () => {
    expect(attackDir(meta, meta.home.id, 1000)).toBe(1)
    expect(attackDir(meta, meta.home.id, meta.periods[1].startMs + 1000)).toBe(-1)
  })
})

describe('the three-step path lives in the URL', () => {
  it('defaults to Watch and ignores unknown steps', () => {
    expect(parseHash('#/?match=x').step).toBe('watch')
    expect(parseHash('#/?step=nonsense').step).toBe('watch')
  })
  it('round-trips the step and the Explore view', () => {
    const r = parseHash('#/?match=x&step=explore&tab=space')
    expect([r.step, r.tab]).toEqual(['explore', 'space'])
    expect(buildHash(r)).toContain('step=explore')
    expect(buildHash(r)).toContain('tab=space')
  })
  it('keeps the address short outside Explore', () => {
    const h = buildHash({ ...parseHash('#/?step=understand&tab=space'), t: null })
    expect(h).toContain('step=understand')
    expect(h).not.toContain('tab=')
    expect(buildHash(parseHash('#/?match=x'))).not.toContain('step=')
  })
})

describe('phases of play', () => {
  const a = { phases: { KES: { segments: [[0, 1], [10_000, 2], [25_000, 3]], share: {}, entries: {}, causes: {}, measured: {} } } } as unknown as Analytics
  it('finds the phase a team is in at any time', () => {
    expect(phaseAt(a, 'KES', 0)).toBe('attack')
    expect(phaseAt(a, 'KES', 9_999)).toBe('attack')
    expect(phaseAt(a, 'KES', 10_000)).toBe('press')
    expect(phaseAt(a, 'KES', 999_999)).toBe('block')
  })
  it('says nothing when the package has no phases', () => {
    expect(phaseAt(a, 'ALD', 5_000)).toBeNull()
    expect(phaseAt(null, 'KES', 5_000)).toBeNull()
  })
})

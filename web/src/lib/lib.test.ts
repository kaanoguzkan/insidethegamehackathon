import { readFileSync } from 'node:fs'
import { gunzipSync } from 'node:zlib'
import { describe, expect, it } from 'vitest'
import { clockAt, totalMs } from './clock'
import { covers } from './cohort'
import { activeAt, isShown, visibleOverlays } from './overlays'
import { isNarrative, overlaysFor, SAFE_ID, type Replay } from './data'
import { recapFor, recapReady } from './recap'
import { maybeGunzip, Tracking } from './tracking'
import { DEFAULT_PROFILE, type Cohort, type Meta, type Overlay, type Profile } from './types'

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

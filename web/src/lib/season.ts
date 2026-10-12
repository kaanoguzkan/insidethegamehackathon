import { BRAIN_URL } from './brain'
import type { LiveMatch } from './live'

/** The season and the channel as the Brain serves them (src/matchmind/live/season_api.py). */

export interface Club {
  name: string
  short: string
  primary: string
  secondary: string
}

export interface Fixture {
  id: string
  round: number
  home: string
  away: string
  scenario: string | null
  status: 'pending' | 'simulating' | 'done'
  score: Record<string, number> | null
}

export interface StandingRow {
  club: string
  name: string
  played: number
  won: number
  drawn: number
  lost: number
  gf: number
  ga: number
  gd: number
  points: number
}

export interface SeasonView {
  seasonId: string | null
  seed?: number
  featured?: boolean
  createdMs?: number
  total: number
  done: number
  simulating: number
  fixtures: Fixture[]
  /** Fixtures that have been played on air to the end: the home page's table counts only these (nothing is spoilt). */
  aired: string[]
  standings: StandingRow[]
  standingsAired: StandingRow[]
  clubs: Record<string, Club>
}

export interface ChannelNow {
  matchId: string
  seasonId: string
  fixtureId: string
  round: number
  speed: number
  heartbeatMs: number
}

/** The Brain is still simulating the season: nothing to show yet, try again. */
export class SeasonWait extends Error {
  constructor() {
    super('the season is being simulated')
  }
}

/** A season is already being simulated; the page should follow that one. */
export class SeasonBusy extends Error {
  constructor(public seasonId: string) {
    super('a season is already being simulated')
  }
}

const json = async <T>(res: Response): Promise<T> => {
  if (!res.ok) throw new Error(`brain: ${res.status}`)
  return (await res.json()) as T
}

export const getSeason = (base = BRAIN_URL, signal?: AbortSignal): Promise<SeasonView> => fetch(`${base}/api/season`, { signal }).then((r) => json<SeasonView>(r))

export async function getChannel(base = BRAIN_URL, signal?: AbortSignal): Promise<{ now: (ChannelNow & { match: LiveMatch }) | null; seasonId: string | null; speeds: number[] }> {
  return fetch(`${base}/api/channel`, { signal }).then((r) => json(r))
}

/** Join the match that is on or start the next fixture. With `next` the match on air is taken off; with `fixtureId` that fixture is played. Throws SeasonWait while no fixture is simulated yet. */
export async function tune(opts: { fixtureId?: string; speed?: number; next?: boolean } = {}, base = BRAIN_URL, signal?: AbortSignal): Promise<ChannelNow> {
  const res = await fetch(`${base}/api/channel/tune`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(opts), signal })
  if (res.status === 503) throw new SeasonWait()
  if (res.status === 429) throw new Error('rate')
  return json<ChannelNow>(res)
}

export async function simulateSeason(base = BRAIN_URL, signal?: AbortSignal): Promise<{ seasonId: string }> {
  const res = await fetch(`${base}/api/season/simulate`, { method: 'POST', signal })
  if (res.status === 409) {
    const body = (await res.json()) as { detail?: { seasonId?: string } }
    if (body.detail?.seasonId) throw new SeasonBusy(body.detail.seasonId)
  }
  if (res.status === 429) throw new Error('rate')
  return json<{ seasonId: string }>(res)
}

/** The fixture's label: "Round 3 · Harbour v Northbridge". */
export function fixtureLabel(f: Pick<Fixture, 'round' | 'home' | 'away'>, clubs: Record<string, Club>): string {
  return `${clubs[f.home]?.short ?? f.home} v ${clubs[f.away]?.short ?? f.away}`
}

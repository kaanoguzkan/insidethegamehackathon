import type { MatchEvent, Meta, Moment, Overlay, Recap, ReplayIndexEntry, Snapshot } from './types'
import { gunzip, type SlotRow, Tracking } from './tracking'

export interface Replay {
  id: string
  meta: Meta
  moments: Moment[]
  overlays: Overlay[]
  snapshots: Snapshot[]
  recaps: Recap[]
  events: MatchEvent[]
  eventsById: Map<string, MatchEvent>
  tracking: Tracking
}

const base = () => `${import.meta.env.BASE_URL}replays/`

async function json<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${url}: ${res.status}`)
  return res.json() as Promise<T>
}

export async function loadIndex(): Promise<ReplayIndexEntry[]> {
  return json<ReplayIndexEntry[]>(`${base()}index.json`)
}

// Replay ids come from the URL hash, so they are restricted to a safe slug before reaching a fetch path.
export const SAFE_ID = /^[a-z0-9][a-z0-9-]{0,63}$/

export async function loadReplay(id: string, root = base()): Promise<Replay> {
  if (!SAFE_ID.test(id)) throw new Error(`invalid match id: ${id}`)
  const dir = `${root}${id}/`
  const [meta, moments, overlays, snapshots, recaps, events, slots, bin] = await Promise.all([
    json<Meta>(`${dir}meta.json`),
    json<Moment[]>(`${dir}moments.json`),
    json<Overlay[]>(`${dir}overlays.json`),
    json<Snapshot[]>(`${dir}snapshots.json`),
    json<Recap[]>(`${dir}recaps.json`).catch(() => [] as Recap[]), // older packages have none
    json<MatchEvent[]>(`${dir}events.json`),
    json<SlotRow[]>(`${dir}slots.json`),
    fetch(`${dir}tracking.bin.gz`).then(gunzip),
  ])
  overlays.sort((a, b) => a.displayAt.matchMs - b.displayAt.matchMs || a.priority - b.priority)
  return {
    id,
    meta,
    moments,
    overlays,
    snapshots,
    recaps,
    events,
    eventsById: new Map(events.map((e) => [e.id, e])),
    tracking: new Tracking(bin, slots),
  }
}

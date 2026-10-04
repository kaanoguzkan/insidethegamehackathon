import type { MatchEvent, Meta, Moment, Overlay, ReplayIndexEntry, Snapshot } from './types'
import { gunzip, type SlotRow, Tracking } from './tracking'

export interface Replay {
  id: string
  meta: Meta
  moments: Moment[]
  overlays: Overlay[]
  snapshots: Snapshot[]
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

export async function loadReplay(id: string, root = base()): Promise<Replay> {
  const dir = `${root}${id}/`
  const [meta, moments, overlays, snapshots, events, slots, bin] = await Promise.all([
    json<Meta>(`${dir}meta.json`),
    json<Moment[]>(`${dir}moments.json`),
    json<Overlay[]>(`${dir}overlays.json`),
    json<Snapshot[]>(`${dir}snapshots.json`),
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
    events,
    eventsById: new Map(events.map((e) => [e.id, e])),
    tracking: new Tracking(bin, slots),
  }
}

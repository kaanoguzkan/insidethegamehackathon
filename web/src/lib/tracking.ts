// Decoder for the single-file tracking bundle (see src/matchmind/tracking/bundle.py).
// Layout: 16-byte header, int16 player positions [frames*22*2] in decimetres (-32768 = off the pitch),
// then int16 ball [frames*4]: x, y, height in decimetres and a 0/1 in-play flag.

export const OFF = -32768
const HEADER = 16

export interface SlotRow {
  fromFrame: number
  ids: string[]
}

export interface PlayerPoint {
  slot: number
  id: string
  x: number
  y: number
}

export interface Frame {
  players: PlayerPoint[]
  ball: { x: number; y: number; z: number; alive: boolean }
}

export class Tracking {
  readonly frames: number
  readonly hz: number
  private pos: Int16Array
  private ball: Int16Array

  constructor(raw: ArrayBuffer, private slots: SlotRow[]) {
    const dv = new DataView(raw)
    const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3))
    if (magic !== 'MMT1') throw new Error('not a MatchMind tracking bundle')
    this.hz = dv.getUint8(5)
    this.frames = dv.getUint32(8, true)
    const players = dv.getUint8(12)
    if (players !== 22) throw new Error(`unexpected player count ${players}`)
    const n = this.frames
    // Copy into aligned arrays: the payload offset (16) is a multiple of 2, but be explicit.
    this.pos = new Int16Array(raw.slice(HEADER, HEADER + n * 22 * 2 * 2))
    this.ball = new Int16Array(raw.slice(HEADER + n * 22 * 2 * 2, HEADER + n * 22 * 2 * 2 + n * 4 * 2))
  }

  /** The player ids occupying the 22 slots at a frame (changes at substitutions). */
  idsAt(frame: number): string[] {
    let lo = 0
    let hi = this.slots.length - 1
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1
      if (this.slots[mid].fromFrame <= frame) lo = mid
      else hi = mid - 1
    }
    return this.slots[lo].ids
  }

  private p(frame: number, slot: number): [number, number] | null {
    const i = (frame * 22 + slot) * 2
    const x = this.pos[i]
    if (x === OFF) return null
    return [x / 10, this.pos[i + 1] / 10]
  }

  /** Interpolated state at a match time in milliseconds (clamped to the recording). */
  at(ms: number): Frame {
    const f = Math.min(this.frames - 1, Math.max(0, (ms / 1000) * this.hz))
    const f0 = Math.floor(f)
    const f1 = Math.min(this.frames - 1, f0 + 1)
    const a = f - f0
    const ids = this.idsAt(f0)
    const players: PlayerPoint[] = []
    for (let s = 0; s < 22; s++) {
      const p0 = this.p(f0, s)
      if (!p0) continue
      const p1 = this.p(f1, s) ?? p0
      players.push({ slot: s, id: ids[s], x: p0[0] + (p1[0] - p0[0]) * a, y: p0[1] + (p1[1] - p0[1]) * a })
    }
    const b0 = f0 * 4
    const b1 = f1 * 4
    const alive = this.ball[b0 + 3] === 1
    // Do not interpolate across a dead-ball reset: the ball is carried to the spot, not flying.
    const t = alive && this.ball[b1 + 3] === 1 ? a : 0
    const bx = (this.ball[b0] + (this.ball[b1] - this.ball[b0]) * t) / 10
    const by = (this.ball[b0 + 1] + (this.ball[b1 + 1] - this.ball[b0 + 1]) * t) / 10
    const bz = (this.ball[b0 + 2] + (this.ball[b1 + 2] - this.ball[b0 + 2]) * t) / 10
    return { players, ball: { x: bx, y: by, z: bz, alive } }
  }
}

/**
 * Fetch a gzip file and return its decompressed bytes.
 *
 * Hosts disagree: some send `Content-Encoding: gzip` for `.gz` files, so the browser has already
 * decompressed the body; others (GitHub Pages) send raw gzip. Sniff the magic number instead of
 * assuming either.
 */
export async function gunzip(res: Response): Promise<ArrayBuffer> {
  if (!res.ok) throw new Error(`${res.url}: ${res.status}`)
  const raw = await res.arrayBuffer()
  return maybeGunzip(raw)
}

export async function maybeGunzip(raw: ArrayBuffer): Promise<ArrayBuffer> {
  const b = new Uint8Array(raw, 0, Math.min(2, raw.byteLength))
  if (b.length < 2 || b[0] !== 0x1f || b[1] !== 0x8b) return raw // already decoded by the browser
  const stream = new Blob([raw]).stream().pipeThrough(new DecompressionStream('gzip'))
  return new Response(stream).arrayBuffer()
}

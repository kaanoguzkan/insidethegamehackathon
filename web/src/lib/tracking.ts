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

/** What the pitch components need from tracking: the recorded bundle and the live chunks both provide it. */
export interface TrackingSource {
  readonly frames: number
  readonly hz: number
  idsAt(frame: number): string[]
  at(ms: number): Frame
}


/**
 * A player's position between two samples. The tracking is 5 samples a second; joining them with straight lines gives paths with corners and a
 * heading that jumps. A Catmull-Rom spline through the neighbouring samples is smooth where the movement is (and passes through every sample).
 * A jump of more than JUMP metres between samples (a substitution, the second-half reposition) is not movement: those stay straight.
 */
const JUMP = 8
export function smoothStep(pm: [number, number] | null, p0: [number, number], p1: [number, number], p2: [number, number] | null, a: number): [number, number] {
  const near = (u: [number, number], v: [number, number]) => Math.hypot(u[0] - v[0], u[1] - v[1]) <= JUMP
  const lin: [number, number] = [p0[0] + (p1[0] - p0[0]) * a, p0[1] + (p1[1] - p0[1]) * a]
  if (!near(p0, p1)) return lin
  // no neighbour (the start or end of the recording, a player who was off the pitch) or a jump: carry on the way the segment goes
  const before: [number, number] = pm && near(pm, p0) ? pm : [2 * p0[0] - p1[0], 2 * p0[1] - p1[1]]
  const after: [number, number] = p2 && near(p1, p2) ? p2 : [2 * p1[0] - p0[0], 2 * p1[1] - p0[1]]
  const cr = (i: number) => 0.5 * (2 * p0[i] + (-before[i] + p1[i]) * a + (2 * before[i] - 5 * p0[i] + 4 * p1[i] - after[i]) * a * a + (-before[i] + 3 * p0[i] - 3 * p1[i] + after[i]) * a * a * a)
  return [cr(0), cr(1)]
}

export class Tracking implements TrackingSource {
  readonly frames: number
  readonly hz: number
  private pos: Int16Array
  private ball: Int16Array

  constructor(raw: ArrayBuffer, private slots: SlotRow[]) {
    const dv = new DataView(raw)
    const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3))
    if (magic !== 'MMT1') throw new Error('not a Rifinitore tracking bundle')
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
    const fm = Math.max(0, f0 - 1)
    const f2 = Math.min(this.frames - 1, f0 + 2)
    const a = f - f0
    const ids = this.idsAt(f0)
    const players: PlayerPoint[] = []
    for (let s = 0; s < 22; s++) {
      const p0 = this.p(f0, s)
      if (!p0) continue
      const p1 = this.p(f1, s) ?? p0
      const [x, y] = smoothStep(f0 > 0 ? this.p(fm, s) : null, p0, p1, f0 + 2 <= this.frames - 1 ? this.p(f2, s) : null, a)
      players.push({ slot: s, id: ids[s], x, y })
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

/** One tracking chunk as the Brain serves it (src/matchmind/tracking/frames.py): five seconds, positions in 1/``scale`` metres, ``null`` for a player off the pitch. */
export interface ChunkJson {
  matchId: string
  chunk: number
  startMs: number
  hz: number
  scale: number
  slots: string[]
  ball: number[][]
  alive: number[]
  players: (number[] | null)[][]
}

interface LiveChunk {
  index: number
  n: number
  slots: string[]
  pos: Int16Array // decimetres, OFF while a player is off the pitch
  ball: Int16Array // x, y, z in decimetres, then the in-play flag
}

/**
 * Tracking that arrives chunk by chunk while the match is played. It answers the same `at(ms)` as the recorded bundle; where a chunk has not arrived
 * it holds the nearest frame it has (the pitch freezes for a moment rather than breaking), and `frames` grows as chunks come in.
 */
export class LiveTracking implements TrackingSource {
  hz = 5
  private perChunk = 0 // learnt from the chunks (25 frames in production)
  private chunks = new Map<number, LiveChunk>()
  private maxIndex = -1

  get frames(): number {
    return (this.maxIndex + 1) * this.perChunk
  }

  has(index: number): boolean {
    return this.chunks.has(index)
  }

  /** The highest chunk index received so far (-1 before the first). */
  get last(): number {
    return this.maxIndex
  }

  addChunk(c: ChunkJson): void {
    const n = c.players.length
    this.hz = c.hz
    this.perChunk = Math.max(this.perChunk, n)
    const k = 10 / c.scale // to decimetres
    const pos = new Int16Array(n * 22 * 2).fill(OFF)
    c.players.forEach((row, i) =>
      row.forEach((p, j) => {
        if (p) {
          pos[(i * 22 + j) * 2] = Math.round(p[0] * k)
          pos[(i * 22 + j) * 2 + 1] = Math.round(p[1] * k)
        }
      }),
    )
    const ball = new Int16Array(n * 4)
    c.ball.forEach((b, i) => {
      ball[i * 4] = Math.round(b[0] * k)
      ball[i * 4 + 1] = Math.round(b[1] * k)
      ball[i * 4 + 2] = Math.round((b[2] ?? 0) * k)
      ball[i * 4 + 3] = c.alive[i] ? 1 : 0
    })
    this.chunks.set(c.chunk, { index: c.chunk, n, slots: c.slots, pos, ball })
    this.maxIndex = Math.max(this.maxIndex, c.chunk)
  }

  /** The chunk and the position inside it for a frame number, falling back to the nearest chunk that has arrived. */
  private locate(frame: number): { ch: LiveChunk; k: number } | null {
    if (this.chunks.size === 0) return null
    let idx = Math.floor(Math.max(0, frame) / this.perChunk)
    let ch = this.chunks.get(idx)
    if (ch) return { ch, k: Math.min(ch.n - 1, Math.max(0, frame - idx * this.perChunk)) }
    // not here (yet): hold the nearest earlier frame, or the earliest one there is
    for (let i = idx - 1; i >= 0; i--) {
      ch = this.chunks.get(i)
      if (ch) return { ch, k: ch.n - 1 }
    }
    idx = Math.min(...this.chunks.keys())
    ch = this.chunks.get(idx)!
    return { ch, k: 0 }
  }

  idsAt(frame: number): string[] {
    return this.locate(frame)?.ch.slots ?? []
  }

  at(ms: number): Frame {
    const f = Math.max(0, (ms / 1000) * this.hz)
    const f0 = Math.floor(f)
    const a = f - f0
    const l0 = this.locate(f0)
    if (!l0) return { players: [], ball: { x: 52.5, y: 34, z: 0, alive: false } }
    const l1 = this.locate(f0 + 1) ?? l0
    const lm = f0 > 0 ? this.locate(f0 - 1) : null
    const l2 = this.locate(f0 + 2)
    const ids = l0.ch.slots
    const at = (l: { ch: LiveChunk; k: number }, s: number): [number, number] | null => {
      const i = (l.k * 22 + s) * 2
      return l.ch.pos[i] === OFF ? null : [l.ch.pos[i] / 10, l.ch.pos[i + 1] / 10]
    }
    const players: PlayerPoint[] = []
    for (let s = 0; s < 22; s++) {
      const p0 = at(l0, s)
      if (!p0) continue
      const p1 = at(l1, s) ?? p0
      const [x, y] = smoothStep(lm ? at(lm, s) : null, p0, p1, l2 ? at(l2, s) : null, a)
      players.push({ slot: s, id: ids[s], x, y })
    }
    const b0 = l0.k * 4
    const b1 = l1.k * 4
    const alive = l0.ch.ball[b0 + 3] === 1
    const t = alive && l1.ch.ball[b1 + 3] === 1 ? a : 0 // no interpolation across a dead-ball reset
    const lerp = (j: number) => (l0.ch.ball[b0 + j] + (l1.ch.ball[b1 + j] - l0.ch.ball[b0 + j]) * t) / 10
    return { players, ball: { x: lerp(0), y: lerp(1), z: lerp(2), alive } }
  }
}

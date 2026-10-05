// Live graphics drawn on the pitch canvas from the tracking frame (pitch control, team shape, offside line,
// passing options, run trails) and the geometry of `pitch_graphic` overlays.
import { homeControl, NX, NY } from './control'
import { defensiveLine, offsideLineX, passingLanes, teamHull, type Pt } from './geometry'
import type { Replay } from './data'
import type { Frame, PlayerPoint } from './tracking'
import type { Graphic, Meta, Overlay, Shape } from './types'

const L = 105
const W = 68

export interface Layers {
  control: boolean
  shape: boolean
  offside: boolean
  lanes: boolean
  runs: boolean
}
export const NO_LAYERS: Layers = { control: false, shape: false, offside: false, lanes: false, runs: false }
export const LAYER_KEYS = ['control', 'shape', 'offside', 'lanes', 'runs'] as const

export interface Labels {
  offside: string
  runs: Record<string, string>
}

type Tx = { X: (x: number) => number; Y: (y: number) => number; s: number }

/** Which way a club attacks at a match time (+1 toward x = 105). */
export function attackDir(meta: Meta, club: string, ms: number): 1 | -1 {
  const p = meta.periods.find((q) => ms >= q.startMs && ms <= q.endMs) ?? meta.periods[0]
  return (p.attackDirection[club] ?? 1) === 1 ? 1 : -1
}

const rgba = (hex: string, a: number) => {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex)
  if (!m) return `rgba(255,255,255,${a})`
  const n = parseInt(m[1], 16)
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`
}

function arrow(ctx: CanvasRenderingContext2D, a: Pt, b: Pt, tx: Tx, head = 9) {
  const x1 = tx.X(a[0])
  const y1 = tx.Y(a[1])
  const x2 = tx.X(b[0])
  const y2 = tx.Y(b[1])
  ctx.beginPath()
  ctx.moveTo(x1, y1)
  ctx.lineTo(x2, y2)
  ctx.stroke()
  const ang = Math.atan2(y2 - y1, x2 - x1)
  ctx.beginPath()
  ctx.moveTo(x2, y2)
  ctx.lineTo(x2 - head * Math.cos(ang - 0.45), y2 - head * Math.sin(ang - 0.45))
  ctx.lineTo(x2 - head * Math.cos(ang + 0.45), y2 - head * Math.sin(ang + 0.45))
  ctx.closePath()
  ctx.fill()
}

export function drawLayers(ctx: CanvasRenderingContext2D, replay: Replay, frame: Frame, ms: number, layers: Layers, carrier: PlayerPoint | null, tx: Tx, labels: Labels) {
  const { meta } = replay
  const homeC = meta.home.colors.primary
  const awayC = meta.away.colors.primary
  if (layers.control) {
    const grid = homeControl(frame.players)
    const cw = (L / NX) * tx.s
    const ch = (W / NY) * tx.s
    for (let iy = 0; iy < NY; iy++) {
      for (let ix = 0; ix < NX; ix++) {
        const p = grid[iy * NX + ix]
        const a = Math.abs(p - 0.5) * 2 * 0.42
        ctx.fillStyle = rgba(p >= 0.5 ? homeC : awayC, a)
        ctx.fillRect(tx.X(ix * (L / NX)), tx.Y(iy * (W / NY)), cw + 0.5, ch + 0.5)
      }
    }
  }
  if (layers.shape) {
    ;([0, 1] as const).forEach((team) => {
      const color = team === 0 ? homeC : awayC
      const club = team === 0 ? meta.home.id : meta.away.id
      const hull = teamHull(frame, team)
      if (hull.length >= 3) {
        ctx.beginPath()
        hull.forEach((p, i) => (i ? ctx.lineTo(tx.X(p[0]), tx.Y(p[1])) : ctx.moveTo(tx.X(p[0]), tx.Y(p[1]))))
        ctx.closePath()
        ctx.fillStyle = rgba(color, 0.13)
        ctx.fill()
        ctx.lineWidth = 1.6
        ctx.strokeStyle = rgba(color, 0.8)
        ctx.stroke()
      }
      const line = defensiveLine(frame, team, attackDir(meta, club, ms))
      if (line.length >= 2) {
        ctx.setLineDash([6, 4])
        ctx.lineWidth = 2.4
        ctx.strokeStyle = rgba(color, 0.95)
        ctx.beginPath()
        line.forEach((p, i) => (i ? ctx.lineTo(tx.X(p[0]), tx.Y(p[1])) : ctx.moveTo(tx.X(p[0]), tx.Y(p[1]))))
        ctx.stroke()
        ctx.setLineDash([])
      }
    })
  }
  if (layers.offside && carrier) {
    const attacking: 0 | 1 = carrier.slot < 11 ? 0 : 1
    const defending: 0 | 1 = attacking === 0 ? 1 : 0
    const defClub = defending === 0 ? meta.home.id : meta.away.id
    const x = offsideLineX(frame, defending, attackDir(meta, defClub, ms))
    if (x !== null) {
      ctx.save()
      ctx.setLineDash([9, 6])
      ctx.lineWidth = 2.2
      ctx.strokeStyle = 'rgba(255,255,255,.9)'
      ctx.beginPath()
      ctx.moveTo(tx.X(x), tx.Y(0))
      ctx.lineTo(tx.X(x), tx.Y(W))
      ctx.stroke()
      ctx.setLineDash([])
      ctx.fillStyle = 'rgba(255,255,255,.92)'
      ctx.font = '700 11px system-ui, sans-serif'
      ctx.textAlign = 'left'
      ctx.fillText(labels.offside, tx.X(x) + 5, tx.Y(3))
      ctx.restore()
    }
  }
  if (layers.lanes && carrier) {
    const club = carrier.slot < 11 ? meta.home.id : meta.away.id
    const lanes = passingLanes(frame, carrier, attackDir(meta, club, ms))
    ctx.save()
    for (const l of lanes) {
      const col = l.block < 0.35 ? '#3ddc97' : l.block < 0.7 ? '#ffb454' : '#ff6b6b'
      ctx.strokeStyle = col
      ctx.fillStyle = col
      ctx.lineWidth = 2.2
      ctx.setLineDash(l.block < 0.35 ? [] : [5, 5])
      arrow(ctx, [carrier.x, carrier.y], [l.to.x, l.to.y], tx, 8)
    }
    ctx.restore()
  }
  if (layers.runs) {
    ctx.save()
    for (const e of replay.events) {
      if (e.type !== 'off_ball_run' || !e.attributes) continue
      const a = e.attributes as { startMs: number; durationMs: number; from: Pt; to: Pt; kind: string }
      if (ms < a.startMs || ms > a.startMs + a.durationMs + 2500) continue
      const club = e.team ?? meta.home.id
      const d = attackDir(meta, club, a.startMs)
      const abs = (p: Pt): Pt => (d === 1 ? p : [L - p[0], W - p[1]])
      const color = club === meta.home.id ? homeC : awayC
      ctx.strokeStyle = '#ffd24a'
      ctx.fillStyle = '#ffd24a'
      ctx.lineWidth = 2.6
      ctx.setLineDash([7, 5])
      arrow(ctx, abs(a.from), abs(a.to), tx, 9)
      ctx.setLineDash([])
      ctx.font = '700 11px system-ui, sans-serif'
      ctx.textAlign = 'center'
      const to = abs(a.to)
      ctx.fillStyle = color
      ctx.fillText(labels.runs[a.kind] ?? a.kind, tx.X(to[0]), tx.Y(to[1]) - 10)
    }
    ctx.restore()
  }
}

const EMPHASIS: Record<Shape['emphasis'], string> = { primary: '#ffd24a', secondary: '#4cc2ff', muted: 'rgba(255,255,255,.6)' }

/** Fade in and out over the first and last 350 ms of the overlay's window. */
export const fade = (o: Overlay, ms: number) => Math.max(0, Math.min(1, (ms - o.displayAt.matchMs) / 350, (o.displayAt.matchMs + o.durationMs - ms) / 350))

export function drawGraphic(ctx: CanvasRenderingContext2D, o: Overlay, ms: number, tx: Tx, reduced: boolean) {
  const g: Graphic | null | undefined = o.graphic
  if (!g) return
  ctx.save()
  ctx.globalAlpha = reduced ? 1 : fade(o, ms)
  for (const sh of g.shapes) {
    const col = EMPHASIS[sh.emphasis]
    ctx.strokeStyle = col
    ctx.fillStyle = col
    ctx.lineWidth = sh.shape === 'arrow' ? 3 : 2.4
    ctx.setLineDash(sh.style === 'dashed' ? [9, 6] : sh.style === 'dotted' ? [2, 5] : [])
    const pts = sh.points.map((p) => [p.x, p.y] as Pt)
    if (sh.shape === 'line' && pts.length >= 2) {
      ctx.beginPath()
      pts.forEach((p, i) => (i ? ctx.lineTo(tx.X(p[0]), tx.Y(p[1])) : ctx.moveTo(tx.X(p[0]), tx.Y(p[1]))))
      ctx.stroke()
      if (sh.label) label(ctx, sh.label, tx.X(pts[0][0]) + 6, tx.Y(5), col)
    } else if (sh.shape === 'arrow' && pts.length >= 2) {
      arrow(ctx, pts[0], pts[pts.length - 1], tx, 10)
      if (sh.label) label(ctx, sh.label, tx.X((pts[0][0] + pts[1][0]) / 2), tx.Y((pts[0][1] + pts[1][1]) / 2) - 8, col)
    } else if (sh.shape === 'polygon' && pts.length >= 3) {
      ctx.beginPath()
      pts.forEach((p, i) => (i ? ctx.lineTo(tx.X(p[0]), tx.Y(p[1])) : ctx.moveTo(tx.X(p[0]), tx.Y(p[1]))))
      ctx.closePath()
      ctx.globalAlpha *= 0.25
      ctx.fill()
      ctx.globalAlpha = reduced ? 1 : fade(o, ms)
      ctx.stroke()
    } else if (sh.shape === 'circle' && pts.length) {
      ctx.beginPath()
      ctx.arc(tx.X(pts[0][0]), tx.Y(pts[0][1]), Math.max(5, (sh.radius ?? 1) * tx.s), 0, Math.PI * 2)
      ctx.stroke()
      if (sh.label) label(ctx, sh.label, tx.X(pts[0][0]), tx.Y(pts[0][1]) - (sh.radius ?? 1) * tx.s - 8, col)
    } else if (sh.shape === 'text' && pts.length && sh.label) {
      label(ctx, sh.label, tx.X(pts[0][0]), tx.Y(pts[0][1]) + 16, col)
    }
  }
  ctx.restore()
}

function label(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, color: string) {
  ctx.save()
  ctx.setLineDash([])
  ctx.font = '700 11.5px system-ui, sans-serif'
  const w = ctx.measureText(text).width + 12
  ctx.beginPath()
  ctx.roundRect(x - w / 2, y - 12, w, 18, 6)
  ctx.fillStyle = 'rgba(10,15,20,.86)'
  ctx.fill()
  ctx.lineWidth = 1.5
  ctx.strokeStyle = color
  ctx.stroke()
  ctx.fillStyle = '#fff'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(text, x, y - 3)
  ctx.restore()
}

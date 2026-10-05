import { useEffect, useRef, type MutableRefObject } from 'react'
import type { Replay } from '../lib/data'
import { drawGraphic, drawLayers, type Labels, type Layers } from '../lib/layers'
import type { MatchEvent, Overlay, TeamMeta } from '../lib/types'

const L = 105
const W = 68
const PAD = 3 // metres of grass around the touchlines
const SPRINT_TAG_KMH = 25 // a speed chip appears on a tagged player above this speed

export interface PitchBadge {
  playerId: string
  text: string
}

interface Props {
  replay: Replay
  msRef: MutableRefObject<number>
  focusPlayer: string | null
  evidence: MatchEvent[] | null
  badges: PitchBadge[]
  layers: Layers
  graphics: Overlay[]
  labels: Labels
  highContrast: boolean
  reducedMotion: boolean
  label: string
}

export function Pitch({ replay, msRef, focusPlayer, evidence, badges, layers, graphics, labels, highContrast, reducedMotion, label }: Props) {
  const wrap = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  // The draw loop reads the latest props through a ref so it never restarts.
  const props = useRef({ focusPlayer, evidence, badges, layers, graphics, labels, highContrast, reducedMotion })
  props.current = { focusPlayer, evidence, badges, layers, graphics, labels, highContrast, reducedMotion }

  useEffect(() => {
    const el = wrap.current
    const cv = canvas.current
    if (!el || !cv) return
    const ctx = cv.getContext('2d')
    if (!ctx) return
    const { meta, tracking } = replay
    const teamOf = (id: string): TeamMeta => (id.startsWith(meta.home.id) ? meta.home : meta.away)
    const info = (id: string) => teamOf(id).players[id]
    let size = { w: 0, h: 0, dpr: 1 }

    const resize = () => {
      const w = el.clientWidth
      const h = Math.round((w * (W + PAD * 2)) / (L + PAD * 2))
      const dpr = Math.min(2, window.devicePixelRatio || 1)
      size = { w, h, dpr }
      cv.width = Math.round(w * dpr)
      cv.height = Math.round(h * dpr)
      cv.style.height = `${h}px`
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(el)

    let raf = 0
    const draw = (now: number) => {
      const { w, h, dpr } = size
      const s = w / (L + PAD * 2)
      const X = (x: number) => (x + PAD) * s
      const Y = (y: number) => (y + PAD) * s
      const p = props.current
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      drawPitch(ctx, w, h, s, p.highContrast)

      const ms = msRef.current
      const f = tracking.at(ms)
      const prev = tracking.at(Math.max(0, ms - 200))
      const prevById = new Map(prev.players.map((q) => [q.id, q]))

      // Ball carrier: the closest player to a live ball.
      let carrier: string | null = null
      let carrierPoint: (typeof f.players)[number] | null = null
      if (f.ball.alive) {
        let best = 2.6
        for (const q of f.players) {
          const d = Math.hypot(q.x - f.ball.x, q.y - f.ball.y)
          if (d < best) {
            best = d
            carrier = q.id
            carrierPoint = q
          }
        }
      }

      // Live graphics sit under the players; overlay graphics from the pipeline too.
      const tx = { X, Y, s }
      drawLayers(ctx, replay, f, ms, p.layers, carrierPoint, tx, p.labels)
      for (const g of p.graphics) drawGraphic(ctx, g, ms, tx, p.reducedMotion)
      // Evidence chain under the players.
      if (p.evidence && p.evidence.length) drawEvidence(ctx, p.evidence, meta.home.id, meta, X, Y, s)

      const r = Math.max(6.5, s * 1.25)
      const tags: { x: number; y: number; text: string; color: string; strong: boolean }[] = []
      for (const q of f.players) {
        const team = teamOf(q.id)
        const isHome = team.id === meta.home.id
        const gk = q.slot % 11 === 0
        const px = X(q.x)
        const py = Y(q.y)
        const isFocus = p.focusPlayer === q.id
        if (isFocus) {
          const pulse = p.reducedMotion ? 0 : (Math.sin(now / 260) + 1) / 2
          ctx.beginPath()
          ctx.arc(px, py, r + 5 + pulse * 3, 0, Math.PI * 2)
          ctx.strokeStyle = '#ffd24a'
          ctx.lineWidth = 2.5
          ctx.stroke()
        }
        ctx.beginPath()
        ctx.arc(px, py, r, 0, Math.PI * 2)
        ctx.fillStyle = gk ? team.colors.secondary : team.colors.primary
        ctx.fill()
        // Shape cue that does not rely on colour: the away side wears a thick light ring.
        ctx.lineWidth = isHome ? 1.6 : 3.2
        ctx.strokeStyle = isHome ? 'rgba(255,255,255,.75)' : '#ffffff'
        ctx.stroke()
        if (r >= 8) {
          ctx.fillStyle = gk ? team.colors.primary : team.colors.secondary
          ctx.font = `700 ${Math.round(r * 0.95)}px system-ui, sans-serif`
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(String(info(q.id)?.number ?? ''), px, py + 0.5)
        }
        // Tag the carrier and the followed player; add a speed chip when sprinting.
        if (q.id === carrier || isFocus) {
          const pq = prevById.get(q.id)
          const kmh = pq && f.ball.alive ? (Math.hypot(q.x - pq.x, q.y - pq.y) / 0.2) * 3.6 : 0
          const nm = info(q.id)?.name?.split(' ').slice(-1)[0] ?? q.id
          const text = kmh >= SPRINT_TAG_KMH ? `${nm}  ${kmh.toFixed(0)} km/h` : nm
          tags.push({ x: px, y: py - r - 6, text, color: team.colors.primary, strong: isFocus })
        }
      }
      for (const b of p.badges) {
        const q = f.players.find((z) => z.id === b.playerId)
        if (q) tags.push({ x: X(q.x), y: Y(q.y) - r - 26, text: b.text, color: '#ffb454', strong: true })
      }
      for (const t of tags) drawTag(ctx, t.x, t.y, t.text, t.color, t.strong, w)

      // Ball with a height shadow.
      const bx = X(f.ball.x)
      const by = Y(f.ball.y)
      ctx.beginPath()
      ctx.arc(bx + f.ball.z * 0.6, by + f.ball.z * 0.9, 3.2, 0, Math.PI * 2)
      ctx.fillStyle = 'rgba(0,0,0,.35)'
      ctx.fill()
      ctx.beginPath()
      ctx.arc(bx, by - f.ball.z * 1.4, 4.2, 0, Math.PI * 2)
      ctx.fillStyle = '#fff'
      ctx.fill()
      ctx.lineWidth = 1.2
      ctx.strokeStyle = '#0b1117'
      ctx.stroke()
      if (!f.ball.alive) {
        ctx.fillStyle = 'rgba(255,255,255,.7)'
        ctx.font = '600 11px system-ui, sans-serif'
        ctx.textAlign = 'left'
        ctx.fillText('BALL OUT', 10, h - 10)
      }
      raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
    }
  }, [replay, msRef])

  return (
    <div ref={wrap} className="pitch-wrap">
      <canvas ref={canvas} role="img" aria-label={label} />
    </div>
  )
}

function drawPitch(ctx: CanvasRenderingContext2D, w: number, h: number, s: number, hc: boolean) {
  const g = ctx.createLinearGradient(0, 0, 0, h)
  g.addColorStop(0, hc ? '#0b3d1f' : '#0e4a2f')
  g.addColorStop(1, hc ? '#08301a' : '#0a3a25')
  ctx.fillStyle = g
  ctx.fillRect(0, 0, w, h)
  const stripes = 14
  for (let i = 0; i < stripes; i += 2) {
    ctx.fillStyle = 'rgba(255,255,255,.035)'
    ctx.fillRect(PAD * s + (i * L * s) / stripes, PAD * s, (L * s) / stripes, W * s)
  }
  const X = (x: number) => (x + PAD) * s
  const Y = (y: number) => (y + PAD) * s
  ctx.strokeStyle = hc ? '#ffffff' : 'rgba(255,255,255,.62)'
  ctx.lineWidth = hc ? 2 : 1.3
  ctx.strokeRect(X(0), Y(0), L * s, W * s)
  ctx.beginPath()
  ctx.moveTo(X(L / 2), Y(0))
  ctx.lineTo(X(L / 2), Y(W))
  ctx.stroke()
  ctx.beginPath()
  ctx.arc(X(L / 2), Y(W / 2), 9.15 * s, 0, Math.PI * 2)
  ctx.stroke()
  for (const side of [0, 1]) {
    const x0 = side ? L - 16.5 : 0
    const x6 = side ? L - 5.5 : 0
    ctx.strokeRect(X(x0), Y(W / 2 - 20.16), 16.5 * s, 40.32 * s)
    ctx.strokeRect(X(x6), Y(W / 2 - 9.16), 5.5 * s, 18.32 * s)
    ctx.beginPath()
    ctx.arc(X(side ? L - 11 : 11), Y(W / 2), 1.2, 0, Math.PI * 2)
    ctx.fillStyle = ctx.strokeStyle
    ctx.fill()
    ctx.beginPath()
    const cx = side ? L - 11 : 11
    const a = Math.acos(5.5 / 9.15)
    ctx.arc(X(cx), Y(W / 2), 9.15 * s, side ? Math.PI - a : -a, side ? Math.PI + a : a)
    ctx.stroke()
  }
  ctx.beginPath()
  ctx.arc(X(L / 2), Y(W / 2), 1.3, 0, Math.PI * 2)
  ctx.fillStyle = ctx.strokeStyle
  ctx.fill()
}

function drawTag(ctx: CanvasRenderingContext2D, x: number, y: number, text: string, color: string, strong: boolean, canvasW: number) {
  ctx.font = `700 ${strong ? 12 : 11}px system-ui, sans-serif`
  const padX = 7
  const tw = ctx.measureText(text).width + padX * 2
  const th = 19
  const cx = Math.min(canvasW - tw / 2 - 4, Math.max(tw / 2 + 4, x))
  const left = cx - tw / 2
  const top = y - th
  ctx.beginPath()
  ctx.roundRect(left, top, tw, th, 6)
  ctx.fillStyle = 'rgba(10,15,20,.88)'
  ctx.fill()
  ctx.lineWidth = strong ? 2 : 1.4
  ctx.strokeStyle = color
  ctx.stroke()
  ctx.fillStyle = '#fff'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(text, cx, top + th / 2 + 0.5)
}

function drawEvidence(
  ctx: CanvasRenderingContext2D,
  events: MatchEvent[],
  homeId: string,
  meta: Replay['meta'],
  X: (x: number) => number,
  Y: (y: number) => number,
  s: number,
) {
  events.forEach((e, i) => {
    if (!e.location) return
    const home = e.team === homeId
    const color = home ? meta.home.colors.primary : meta.away.colors.primary
    const x = X(e.location.x)
    const y = Y(e.location.y)
    ctx.save()
    ctx.lineWidth = 3
    ctx.strokeStyle = '#ffd24a'
    ctx.fillStyle = '#ffd24a'
    if (e.end) {
      const x2 = X(e.end.x)
      const y2 = Y(e.end.y)
      ctx.setLineDash(e.type === 'shot' ? [] : [7, 5])
      ctx.lineWidth = e.type === 'shot' ? 4 : 2.5
      ctx.beginPath()
      ctx.moveTo(x, y)
      ctx.lineTo(x2, y2)
      ctx.stroke()
      ctx.setLineDash([])
      const ang = Math.atan2(y2 - y, x2 - x)
      ctx.beginPath()
      ctx.moveTo(x2, y2)
      ctx.lineTo(x2 - 9 * Math.cos(ang - 0.45), y2 - 9 * Math.sin(ang - 0.45))
      ctx.lineTo(x2 - 9 * Math.cos(ang + 0.45), y2 - 9 * Math.sin(ang + 0.45))
      ctx.closePath()
      ctx.fill()
    }
    ctx.beginPath()
    ctx.arc(x, y, Math.max(8, s * 1.5), 0, Math.PI * 2)
    ctx.fillStyle = color
    ctx.fill()
    ctx.lineWidth = 2.5
    ctx.strokeStyle = '#ffd24a'
    ctx.stroke()
    ctx.fillStyle = '#fff'
    ctx.font = '800 11px system-ui, sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(String(i + 1), x, y + 0.5)
    ctx.restore()
  })
}

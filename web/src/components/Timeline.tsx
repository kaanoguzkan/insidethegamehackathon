import { useRef } from 'react'
import { t } from '../i18n'
import { totalMs } from '../lib/clock'
import type { Replay } from '../lib/data'
import type { Lang } from '../lib/types'

const W = 640
const ROW_H = 54
const PAD_X = 4

const TYPE_COLOR: Record<string, string> = {
  goal: '#3ddc97', red_card: '#ff6b6b', penalty: '#ff9f5a', big_chance: '#ffd24a',
  pressure_collapse: '#4cc2ff', pressure_surge: '#4cc2ff', momentum_swing: '#b794f6',
  chaos_flip: '#8da2b5', rhythm_break: '#8da2b5', tactical_shift: '#8da2b5', fatigue_drop: '#8da2b5', physical_highlight: '#566a7c',
}

interface Props {
  replay: Replay
  ms: number
  lang: Lang
  seek: (ms: number) => void
  onPick: (momentId: string) => void
  selected: string | null
}

export function Timeline({ replay, ms, lang, seek, onPick, selected }: Props) {
  const total = totalMs(replay.meta)
  const x = (v: number) => PAD_X + (v / total) * (W - PAD_X * 2)
  const snaps = replay.snapshots
  const { home, away } = replay.meta
  const ref = useRef<SVGSVGElement>(null)

  const line = (get: (s: (typeof snaps)[number]) => number, lo: number, hi: number, rowTop: number) =>
    snaps.map((s, i) => `${i ? 'L' : 'M'}${x(s.matchMs).toFixed(1)} ${(rowTop + ROW_H - 6 - ((get(s) - lo) / (hi - lo)) * (ROW_H - 12)).toFixed(1)}`).join(' ')

  const mid = (rowTop: number) => rowTop + ROW_H / 2
  // Momentum: home share above the middle line, away below.
  const area = (above: boolean, rowTop: number) => {
    const pts = snaps.map((s) => {
      const share = s.momentum[home.id]
      const d = (share - 0.5) * (ROW_H - 12)
      const y = mid(rowTop) - (above ? Math.max(0, d) : Math.min(0, d))
      return [x(s.matchMs), y] as const
    })
    if (!pts.length) return ''
    return `M${pts[0][0]} ${mid(rowTop)} ` + pts.map(([px, py]) => `L${px.toFixed(1)} ${py.toFixed(1)}`).join(' ') + ` L${pts[pts.length - 1][0]} ${mid(rowTop)} Z`
  }

  const onPointer = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = ref.current!.getBoundingClientRect()
    const v = ((e.clientX - r.left) / r.width) * W
    seek(Math.max(0, Math.min(total, ((v - PAD_X) / (W - PAD_X * 2)) * total)))
  }

  const rows = [t(lang, 'momentum'), t(lang, 'chaos'), t(lang, 'pressure')]
  const H = ROW_H * 3 + 26
  const p2 = replay.meta.periods.find((p) => p.period === 2)

  return (
    <svg
      ref={ref}
      className="timeline"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={t(lang, 'timelines')}
      onPointerDown={(e) => {
        ;(e.target as Element).setPointerCapture?.(e.pointerId)
        onPointer(e)
      }}
      onPointerMove={(e) => e.buttons === 1 && onPointer(e)}
    >
      {rows.map((label, i) => (
        <g key={label}>
          <rect x={PAD_X} y={22 + i * ROW_H} width={W - PAD_X * 2} height={ROW_H - 4} rx="6" className="tl-row" />
          <text x={10} y={22 + i * ROW_H + 14} className="tl-label">{label}</text>
        </g>
      ))}
      {/* momentum */}
      <path d={area(true, 22)} fill={home.colors.primary} opacity="0.85" />
      <path d={area(false, 22)} fill={away.colors.primary} opacity="0.85" />
      <line x1={PAD_X} x2={W - PAD_X} y1={mid(22)} y2={mid(22)} className="tl-mid" />
      {/* chaos */}
      <line x1={PAD_X} x2={W - PAD_X} y1={22 + ROW_H + ROW_H / 2} y2={22 + ROW_H + ROW_H / 2} className="tl-mid" />
      <path d={line((s) => s.chaos, 0, 100, 22 + ROW_H)} fill="none" stroke="#ffd24a" strokeWidth="2" />
      {/* pressure */}
      <path d={line((s) => s.pressure[home.id], 0, 100, 22 + ROW_H * 2)} fill="none" stroke={home.colors.primary} strokeWidth="2" />
      <path d={line((s) => s.pressure[away.id], 0, 100, 22 + ROW_H * 2)} fill="none" stroke={away.colors.primary} strokeWidth="2" strokeDasharray="5 3" />
      {p2 && <line x1={x(p2.startMs)} x2={x(p2.startMs)} y1={18} y2={H - 4} className="tl-half" />}
      {/* moment markers */}
      {replay.moments
        .filter((m) => m.salience >= 0.4)
        .map((m) => (
          <g key={m.id} onPointerDown={(e) => { e.stopPropagation(); onPick(m.id) }} className="tl-marker" tabIndex={0} role="button" aria-label={`${m.detectedAt.label} ${m.type.replace(/_/g, ' ')}`} onKeyDown={(e) => e.key === 'Enter' && onPick(m.id)}>
            <title>{`${m.detectedAt.label} ${m.type.replace(/_/g, ' ')}`}</title>
            <circle cx={x(m.detectedAt.matchMs)} cy={11} r={m.id === selected ? 8 : 4 + m.salience * 3} fill={TYPE_COLOR[m.type] ?? '#8da2b5'} stroke={m.id === selected ? '#fff' : 'none'} strokeWidth="2" />
          </g>
        ))}
      <line x1={x(ms)} x2={x(ms)} y1={0} y2={H} className="tl-head" />
    </svg>
  )
}

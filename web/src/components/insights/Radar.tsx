import { t } from '../../i18n'
import type { Lang } from '../../lib/types'

export interface RadarSeries {
  color: string
  label: string
  values: number[] // 0..1 per axis
}

/** A radar chart: axes are i18n keys, values are 0-1 (percentiles or scaled style). */
export function Radar({ axes, series, lang, prefix }: { axes: string[]; series: RadarSeries[]; lang: Lang; prefix: 'ax' | 'tax' }) {
  const R = 78
  const C = 105
  const n = axes.length
  const pt = (i: number, v: number) => {
    const ang = -Math.PI / 2 + (i * 2 * Math.PI) / n
    return [C + Math.cos(ang) * R * v, C + Math.sin(ang) * R * v] as const
  }
  const ring = (v: number) => axes.map((_, i) => pt(i, v).map((x) => x.toFixed(1)).join(',')).join(' ')
  return (
    <svg className="radar" viewBox="-75 -6 360 222" role="img" aria-label={series.map((s) => s.label).join(' / ')}>
      {[0.25, 0.5, 0.75, 1].map((v) => (
        <polygon key={v} points={ring(v)} className={v === 0.5 ? 'rd-ring mid' : 'rd-ring'} />
      ))}
      {axes.map((a, i) => {
        const [x, y] = pt(i, 1)
        const [lx, ly] = pt(i, 1.17)
        return (
          <g key={a}>
            <line x1={C} y1={C} x2={x} y2={y} className="rd-spoke" />
            <text x={lx} y={ly} className="rd-label" textAnchor={lx < C - 6 ? 'end' : lx > C + 6 ? 'start' : 'middle'} dominantBaseline="middle">
              {t(lang, `${prefix}.${a}`)}
            </text>
          </g>
        )
      })}
      {series.map((s) => (
        <polygon key={s.label} points={s.values.map((v, i) => pt(i, Math.max(0.03, v)).map((x) => x.toFixed(1)).join(',')).join(' ')} fill={s.color} fillOpacity={0.28} stroke={s.color} strokeWidth={2} />
      ))}
    </svg>
  )
}

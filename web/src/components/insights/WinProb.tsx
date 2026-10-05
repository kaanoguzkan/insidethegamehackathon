import { t } from '../../i18n'
import { clockAt, totalMs } from '../../lib/clock'
import { pct, winProbAt } from '../../lib/analytics'
import { clubs, colorOf, Explain, shortOf, type ViewProps } from './common'

const W = 640
const H = 190
const PX = 6

export function WinProbView({ replay, a, lang, ms }: ViewProps) {
  const total = totalMs(replay.meta)
  const x = (v: number) => PX + (v / total) * (W - PX * 2)
  const y = (p: number) => 10 + (1 - p) * (H - 24)
  const [home, away] = clubs(replay)
  const pts = a.winProbability.series
  // Stacked from the bottom: home, then the draw band, then away on top.
  const path = (upper: (p: (typeof pts)[number]) => number, lower: (p: (typeof pts)[number]) => number) =>
    `M${pts.map((p) => `${x(p.matchMs).toFixed(1)} ${y(upper(p)).toFixed(1)}`).join(' L')} L${[...pts].reverse().map((p) => `${x(p.matchMs).toFixed(1)} ${y(lower(p)).toFixed(1)}`).join(' L')} Z`
  const now = winProbAt(a, ms)
  const pre = a.winProbability.preMatch
  return (
    <div>
      <h3>{t(lang, 'wp.title')}</h3>
      <Explain>{t(lang, 'wp.explain')}</Explain>
      <svg className="wp-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t(lang, 'wp.title')}>
        <path d={path((p) => p.p.home, () => 0)} fill={colorOf(replay, home.id)} opacity="0.9" />
        <path d={path((p) => p.p.home + p.p.draw, (p) => p.p.home)} className="wp-draw" />
        <path d={path(() => 1, (p) => p.p.home + p.p.draw)} fill={colorOf(replay, away.id)} opacity="0.9" />
        {[0.25, 0.5, 0.75].map((g) => (
          <line key={g} x1={PX} x2={W - PX} y1={y(g)} y2={y(g)} className="wp-grid" />
        ))}
        {a.winProbability.swings.map((s) => {
          const scorer = s.kind === 'goal' ? (s.after.home - s.before.home >= s.after.away - s.before.away ? 'home' : 'away') : 'home'
          const delta = s.after[scorer] - s.before[scorer]
          return (
            <g key={`${s.matchMs}-${s.kind}`}>
              <line x1={x(s.matchMs)} x2={x(s.matchMs)} y1={4} y2={H - 14} className="wp-mark" />
              <text x={x(s.matchMs) + (x(s.matchMs) > W * 0.88 ? -3 : 3)} y={13} className="wp-mark-label" textAnchor={x(s.matchMs) > W * 0.88 ? 'end' : 'start'}>
                {s.kind === 'goal' ? '⚽' : '🟥'} {delta >= 0 ? '+' : ''}{Math.round(delta * 100)}%
              </text>
            </g>
          )
        })}
        <line x1={x(ms)} x2={x(ms)} y1={0} y2={H} className="tl-head" />
      </svg>
      <div className="wp-legend">
        <span><i style={{ background: colorOf(replay, home.id) }} /> {home.short} {now ? pct(now.home) : ''}</span>
        <span><i className="draw" /> {t(lang, 'wp.draw')} {now ? pct(now.draw) : ''}</span>
        <span><i style={{ background: colorOf(replay, away.id) }} /> {away.short} {now ? pct(now.away) : ''}</span>
        {pre && <span className="muted">{t(lang, 'wp.pre')}: {pct(pre.home)} · {pct(pre.draw)} · {pct(pre.away)}</span>}
      </div>
      <h4>{t(lang, 'wp.swings')}</h4>
      <ul className="swing-list">
        {a.winProbability.swings.map((s) => (
          <li key={`${s.matchMs}-${s.kind}`}>
            <b>{clockAt(replay.meta, s.matchMs).label}</b> {s.kind === 'goal' ? t(lang, 'wp.goal') : t(lang, 'wp.red')}
            <span className="muted">
              {' '}{shortOf(replay, home.id)} {pct(s.before.home)} → {pct(s.after.home)} · {t(lang, 'wp.draw')} {pct(s.before.draw)} → {pct(s.after.draw)} · {shortOf(replay, away.id)} {pct(s.before.away)} → {pct(s.after.away)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

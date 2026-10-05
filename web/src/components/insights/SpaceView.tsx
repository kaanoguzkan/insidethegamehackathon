import { t } from '../../i18n'
import { totalMs } from '../../lib/clock'
import { pct } from '../../lib/analytics'
import { clubs, colorOf, Explain, f1, Versus, type ViewProps } from './common'

const W = 640
const H = 150

/** Moving average over ``k`` points so the 30-second samples read as a trend. */
const smooth = (v: number[], k: number) => v.map((_, i) => {
  const s = v.slice(Math.max(0, i - k + 1), i + 1)
  return s.reduce((x, y) => x + y, 0) / s.length
})

export function SpaceView({ replay, a, lang, ms }: ViewProps) {
  const total = totalMs(replay.meta)
  const [home, away] = clubs(replay)
  const x = (v: number) => 6 + (v / total) * (W - 12)
  const y = (v: number) => 8 + (1 - v) * (H - 22)
  const line = (club: string) => {
    const s = a.space.series[club]
    const sm = smooth(s.map((p) => p.control), 8)
    return s.map((p, i) => `${i ? 'L' : 'M'}${x(p.ms).toFixed(1)} ${y(sm[i]).toFixed(1)}`).join(' ')
  }
  const sumH = a.space.teams[home.id]
  const sumA = a.space.teams[away.id]
  return (
    <div>
      <h3>{t(lang, 'spc.control')}</h3>
      <Explain>{t(lang, 'spc.explain')}</Explain>
      <svg className="wp-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t(lang, 'spc.control')}>
        <line x1={6} x2={W - 6} y1={y(0.5)} y2={y(0.5)} className="wp-grid" />
        {[home.id, away.id].map((c, i) => (
          <path key={c} d={line(c)} fill="none" stroke={colorOf(replay, c)} strokeWidth="2.6" strokeDasharray={i ? '6 4' : undefined} />
        ))}
        <line x1={x(ms)} x2={x(ms)} y1={0} y2={H} className="tl-head" />
      </svg>
      <div className="versus-list">
        <Versus label={t(lang, 'spc.control')} a={sumH.controlShare ?? 0} b={sumA.controlShare ?? 0} colorA={colorOf(replay, home.id)} colorB={colorOf(replay, away.id)} fmt={(v) => pct(v)} />
        <Versus label={t(lang, 'spc.third')} a={sumH.finalThirdControl ?? 0} b={sumA.finalThirdControl ?? 0} colorA={colorOf(replay, home.id)} colorB={colorOf(replay, away.id)} fmt={(v) => pct(v)} />
        {sumH.blockAreaM2 != null && sumA.blockAreaM2 != null && (
          <Versus label={`${t(lang, 'spc.block')} (${t(lang, 'spc.m2')})`} a={sumH.blockAreaM2} b={sumA.blockAreaM2} colorA={colorOf(replay, home.id)} colorB={colorOf(replay, away.id)} fmt={(v) => f1(v, 0)} />
        )}
        <Versus label={`${t(lang, 'spc.behind')} (${t(lang, 'spc.m2')})`} a={sumH.spaceBehindM2 ?? 0} b={sumA.spaceBehindM2 ?? 0} colorA={colorOf(replay, home.id)} colorB={colorOf(replay, away.id)} fmt={(v) => f1(v, 0)} />
      </div>
      <Explain>{t(lang, 'spc.behindExplain')}</Explain>
      {sumH.blockAreaM2 != null && <Explain>{t(lang, 'spc.blockExplain')}</Explain>}
    </div>
  )
}

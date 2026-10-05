import { t } from '../../i18n'
import { pct } from '../../lib/analytics'
import { clubs, colorOf, Explain, Versus, type ViewProps } from './common'

export function TransitionsView({ replay, a, lang }: ViewProps) {
  const [home, away] = clubs(replay)
  const th = a.transitions[home.id]
  const ta = a.transitions[away.id]
  const ch = colorOf(replay, home.id)
  const ca = colorOf(replay, away.id)
  const ph = a.pressing[home.id]
  const pa = a.pressing[away.id]
  return (
    <div className="ins-grid">
      <section>
        <h3>{t(lang, 'tab.trans')}</h3>
        <Explain>{t(lang, 'tr.explain')}</Explain>
        <div className="versus-list">
          <Versus label={t(lang, 'tr.lost')} a={th.lost} b={ta.lost} colorA={ch} colorB={ca} />
          <Versus label={t(lang, 'tr.regain')} a={th.regained5s} b={ta.regained5s} colorA={ch} colorB={ca} />
          <Versus label={t(lang, 'tr.rate')} a={th.counterpressRate ?? 0} b={ta.counterpressRate ?? 0} colorA={ch} colorB={ca} fmt={(v) => pct(v)} />
          <Versus label={t(lang, 'tr.high')} a={th.highTurnovers} b={ta.highTurnovers} colorA={ch} colorB={ca} />
          <Versus label={`${t(lang, 'tr.high')} ${t(lang, 'tr.highshot')}`} a={th.highTurnoverShots} b={ta.highTurnoverShots} colorA={ch} colorB={ca} />
          <Versus label={t(lang, 'tr.quick')} a={th.quickEntries} b={ta.quickEntries} colorA={ch} colorB={ca} />
          <Versus label={t(lang, 'tr.fast')} a={th.fastBreaks} b={ta.fastBreaks} colorA={ch} colorB={ca} />
        </div>
      </section>
      <section>
        <h3>{t(lang, 'pr.zones')}</h3>
        <div className="versus-list">
          {(['high', 'middle', 'low'] as const).map((z) => (
            <Versus key={z} label={t(lang, `pr.${z}`)} a={ph.zoneShare[z]} b={pa.zoneShare[z]} colorA={ch} colorB={ca} fmt={(v) => pct(v)} />
          ))}
        </div>
        <h4>{t(lang, 'pr.ppda')}</h4>
        <div className="versus-list">
          {(['high', 'middle', 'low'] as const).map((z) => (
            <Versus key={z} label={t(lang, `pr.${z}`)} a={ph.ppdaByZone?.[z] ?? 0} b={pa.ppdaByZone?.[z] ?? 0} colorA={ch} colorB={ca} fmt={(v) => (v ? v.toFixed(1) : '–')} />
          ))}
        </div>
        <Explain>{t(lang, 'pr.ppdaExplain')}</Explain>
        <h4>{t(lang, 'pr.triggers')}</h4>
        <div className="versus-list">
          {(['backPass', 'badPass', 'other'] as const).map((z) => (
            <Versus key={z} label={t(lang, `pr.${z}`)} a={ph.triggerShare[z]} b={pa.triggerShare[z]} colorA={ch} colorB={ca} fmt={(v) => pct(v)} />
          ))}
        </div>
      </section>
    </div>
  )
}

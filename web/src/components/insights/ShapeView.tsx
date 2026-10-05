import { t } from '../../i18n'
import { clockAt } from '../../lib/clock'
import { clubs, colorOf, Explain, PitchSvg, surname, type ViewProps } from './common'

export function ShapeView({ replay, a, lang }: ViewProps) {
  return (
    <div>
      <Explain>{t(lang, 'shp.explain')}</Explain>
      <div className="ins-grid">
        {clubs(replay).map((team) => {
          const s = a.shapes[team.id]
          if (!s) return null
          const color = colorOf(replay, team.id)
          return (
            <section key={team.id}>
              <h3>{team.short} <span className="muted">{t(lang, 'shp.nominal')} {s.nominal}</span></h3>
              <table className="ins-table compact">
                <thead>
                  <tr><th /><th>{t(lang, 'shp.designed')}</th><th>{t(lang, 'shp.measured')}</th></tr>
                </thead>
                <tbody>
                  <tr><th scope="row">{t(lang, 'shp.def')}</th><td className="n">{s.designed?.block ?? '–'}</td><td className="n"><b>{s.def.measured?.label ?? '–'}</b></td></tr>
                  <tr><th scope="row">{t(lang, 'shp.ip')}</th><td className="n">{s.designed?.attack ?? '–'}</td><td className="n"><b>{s.ip.measured?.label ?? '–'}</b></td></tr>
                </tbody>
              </table>
              <div className="shotmaps">
                {(['def', 'ip'] as const).map((phase) => (
                  <figure key={phase}>
                    <figcaption>{t(lang, `shp.${phase}`)}</figcaption>
                    <PitchSvg label={`${team.short} ${t(lang, `shp.${phase}`)}`}>
                      {s[phase].players.map((p) => (
                        <g key={p.id}>
                          <circle cx={p.x} cy={p.y} r={2.3} fill={color} stroke="#fff" strokeWidth="0.5" />
                          <text x={p.x} y={p.y - 3.4} className="ps-text" textAnchor="middle">{surname(p.name)}</text>
                        </g>
                      ))}
                    </PitchSvg>
                  </figure>
                ))}
              </div>
              {s.blocks.length > 0 && (
                <>
                  <h4>{t(lang, 'shp.blocks')}</h4>
                  <ul className="block-list">
                    {s.blocks.map((b) => (
                      <li key={b.block}><b>{clockAt(replay.meta, b.endMs).label}</b> {b.def ?? '–'} · {b.ip ?? '–'}</li>
                    ))}
                  </ul>
                </>
              )}
            </section>
          )
        })}
      </div>
    </div>
  )
}

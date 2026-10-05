import { useState } from 'react'
import { t } from '../../i18n'
import { Radar } from './Radar'
import { colorOf, Explain, f1, shortOf, type ViewProps } from './common'

export function PlayersView({ replay, a, lang }: ViewProps) {
  const ids = a.players.filter((p) => a.radars?.[p.id]).map((p) => p.id)
  const [pick, setPick] = useState<string>(a.playerOfTheMatch && ids.includes(a.playerOfTheMatch.id) ? a.playerOfTheMatch.id : (ids[0] ?? ''))
  const row = a.players.find((p) => p.id === pick)
  const radar = a.radars?.[pick]
  if (!row || !radar) return <p className="muted">{t(lang, 'ply.none')}</p>
  const color = colorOf(replay, row.team)
  return (
    <div className="ins-grid">
      <section>
        <label className="field">
          <span>{t(lang, 'ply.pick')}</span>
          <select value={pick} onChange={(e) => setPick(e.target.value)}>
            {ids.map((id) => {
              const p = a.players.find((q) => q.id === id)!
              return <option key={id} value={id}>{p.name} · {shortOf(replay, p.team)} · {p.pos}</option>
            })}
          </select>
        </label>
        <h3>{row.name} <span className="muted">{shortOf(replay, row.team)} · {row.pos}</span></h3>
        <Explain>{t(lang, 'ply.radar')}</Explain>
        <Radar axes={radar.axes.map((x) => x.key)} series={[{ color, label: row.name, values: radar.axes.map((x) => x.pct) }]} lang={lang} prefix="ax" />
      </section>
      <section>
        <h4>{t(lang, 'ply.match')}</h4>
        <dl className="kv">
          <dt>{t(lang, 'col.goals')} / {t(lang, 'col.assists')}</dt><dd>{row.goals} / {row.assists}</dd>
          <dt>{t(lang, 'sh.shots')} · xG</dt><dd>{row.shots} · {f1(row.xg, 2)}</dd>
          <dt>{t(lang, 'col.keyp')} · xA</dt><dd>{row.keyPasses} · {f1(row.xa, 2)}</dd>
          <dt>{t(lang, 'val.value')}</dt><dd>{f1(row.value, 2)}</dd>
          <dt>{t(lang, 'col.packing')} · {t(lang, 'col.lines')}</dt><dd>{row.packing} · {row.lineBreaks}</dd>
          <dt>{t(lang, 'rl.km')}</dt><dd>{f1(row.km, 1)}</dd>
        </dl>
        <h4>{t(lang, 'ply.similar')}</h4>
        <ul className="similar">
          {radar.similar.map((s) => (
            <li key={s.id}><span className="dot" style={{ background: colorOf(replay, s.team) }} /> <b>{s.name}</b> <span className="muted">{shortOf(replay, s.team)} · {Math.round(s.similarity * 100)}%</span></li>
          ))}
        </ul>
        <table className="ins-table compact">
          <thead>
            <tr><th /><th>{t(lang, 'ply.per90')}</th><th>{t(lang, 'ply.pctl')}</th></tr>
          </thead>
          <tbody>
            {radar.axes.map((x) => (
              <tr key={x.key}><th scope="row">{t(lang, `ax.${x.key}`)}</th><td className="n">{f1(x.value, 2)}</td><td className="n">{Math.round(x.pct * 100)}</td></tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}

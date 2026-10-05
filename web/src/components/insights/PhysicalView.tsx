import { t } from '../../i18n'
import { clubs, colorOf, Explain, f1, shortOf, type ViewProps } from './common'

const KINDS = ['in_behind', 'overlap', 'drop'] as const

export function PhysicalView({ replay, a, lang }: ViewProps) {
  const [home, away] = clubs(replay)
  const top = a.load.top
  return (
    <div className="ins-grid">
      <section>
        <h3>{t(lang, 'rl.runs')}</h3>
        <table className="ins-table">
          <thead>
            <tr><th />{[home, away].map((c) => <th key={c.id}>{c.short}</th>)}</tr>
          </thead>
          <tbody>
            {KINDS.map((k) => (
              <tr key={k}>
                <th scope="row">{t(lang, `run.${k}`)}</th>
                {[home, away].map((c) => {
                  const r = a.runs.teams[c.id]?.[k]
                  return <td key={c.id} className="n">{r?.n ?? 0} <span className="muted">({r?.ballPlayed ?? 0} {t(lang, 'rl.played')})</span></td>
                })}
              </tr>
            ))}
          </tbody>
        </table>
        <h3>{t(lang, 'rl.lb')}</h3>
        <table className="ins-table">
          <thead>
            <tr><th />{[home, away].map((c) => <th key={c.id}>{c.short}</th>)}</tr>
          </thead>
          <tbody>
            <tr><th scope="row">{t(lang, 'rl.lb')}</th>{[home, away].map((c) => <td key={c.id} className="n">{a.lineBreaks.teams[c.id].lineBreaks}</td>)}</tr>
            <tr><th scope="row">{t(lang, 'rl.three')}</th>{[home, away].map((c) => <td key={c.id} className="n">{a.lineBreaks.teams[c.id].threeLines}</td>)}</tr>
            <tr><th scope="row">{t(lang, 'rl.packing')}</th>{[home, away].map((c) => <td key={c.id} className="n">{a.lineBreaks.teams[c.id].packing}</td>)}</tr>
          </tbody>
        </table>
      </section>
      <section>
        <h3>{t(lang, 'rl.load')}</h3>
        <table className="ins-table">
          <thead>
            <tr><th>{t(lang, 'col.player')}</th><th>{t(lang, 'rl.km')}</th><th>{t(lang, 'rl.hsr')}</th><th>{t(lang, 'rl.sprint')}</th><th>{t(lang, 'rl.acc')}</th><th>{t(lang, 'rl.fatigue')}</th></tr>
          </thead>
          <tbody>
            {top.map((p) => (
              <tr key={p.id}>
                <th scope="row"><span className="dot" style={{ background: colorOf(replay, p.team) }} /> {p.name} <span className="muted">{shortOf(replay, p.team)}</span></th>
                <td className="n">{f1(p.km, 1)}</td>
                <td className="n">{p.hsrM}</td>
                <td className="n">{p.sprintM}</td>
                <td className="n">{p.acc}</td>
                <td className="n">{f1(a.load.players[p.id]?.fatigue, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <Explain>{t(lang, 'rl.fatigueExplain')}</Explain>
      </section>
    </div>
  )
}

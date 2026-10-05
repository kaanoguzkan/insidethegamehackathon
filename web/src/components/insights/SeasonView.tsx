import { t } from '../../i18n'
import { pct } from '../../lib/analytics'
import { Radar } from './Radar'
import { clubs, colorOf, Explain, f1, playerName, shortOf, type ViewProps } from './common'

export function SeasonView({ replay, a, lang }: ViewProps) {
  const s = a.season
  if (!s) return <p className="muted">{t(lang, 'noAnalytics')}</p>
  const [home, away] = clubs(replay)
  const pred = s.prediction
  const rec = s.records
  const tr = a.teamRadars
  return (
    <div className="ins-grid">
      <section>
        <h3>{t(lang, 'se.pred')}</h3>
        <Explain>{t(lang, 'se.predExplain')}</Explain>
        <div className="predbar" role="img" aria-label={`${home.short} ${pct(pred.home)}, ${t(lang, 'wp.draw')} ${pct(pred.draw)}, ${away.short} ${pct(pred.away)}`}>
          <i style={{ width: `${pred.home * 100}%`, background: colorOf(replay, home.id) }}>{pct(pred.home)}</i>
          <i className="draw" style={{ width: `${pred.draw * 100}%` }}>{pct(pred.draw)}</i>
          <i style={{ width: `${pred.away * 100}%`, background: colorOf(replay, away.id) }}>{pct(pred.away)}</i>
        </div>
        <dl className="kv">
          <dt>{t(lang, 'se.xg')}</dt><dd>{home.short} {f1(pred.xg[home.id], 2)} · {away.short} {f1(pred.xg[away.id], 2)}</dd>
          <dt>{t(lang, 'se.scores')}</dt><dd>{pred.scores.map((x) => `${x.score[0]}-${x.score[1]} (${pct(x.p)})`).join(' · ')}</dd>
        </dl>
        <h3>{t(lang, 'se.table')}</h3>
        <table className="ins-table compact">
          <thead>
            <tr><th>#</th><th /><th>{t(lang, 'se.p')}</th><th>{t(lang, 'se.w')}</th><th>{t(lang, 'se.d')}</th><th>{t(lang, 'se.l')}</th><th>{t(lang, 'se.gd')}</th><th>{t(lang, 'se.pts')}</th></tr>
          </thead>
          <tbody>
            {s.standings.map((r) => (
              <tr key={r.club} className={r.club === home.id || r.club === away.id ? 'potm' : ''}>
                <td className="n">{r.pos}</td>
                <th scope="row"><span className="dot" style={{ background: colorOf(replay, r.club) }} /> {shortOf(replay, r.club)}</th>
                <td className="n">{r.played}</td><td className="n">{r.won}</td><td className="n">{r.drawn}</td><td className="n">{r.lost}</td><td className="n">{r.gd}</td><td className="n"><b>{r.pts}</b></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section>
        <h3>{t(lang, 'se.form')}</h3>
        {[home, away].map((c) => (
          <div key={c.id} className="formrow">
            <span>{c.short}</span>
            <span className="pills">{(s.form[c.id] ?? '').split('').map((r, i) => <i key={i} className={`pill ${r}`}>{r}</i>)}</span>
            <span className="muted">{s.streaks[c.id].unbeaten} {t(lang, 'se.unbeaten')} · {s.streaks[c.id].cleanSheets} {t(lang, 'se.clean')}</span>
          </div>
        ))}
        <h4>{t(lang, 'se.h2h')}</h4>
        <ul className="block-list">
          {s.headToHead.meetings.map((m, i) => (
            <li key={i}><b>{m.season}</b> {shortOf(replay, m.home)} {m.score[0]}–{m.score[1]} {shortOf(replay, m.away)}</li>
          ))}
        </ul>
        <h4>{t(lang, 'se.top')}</h4>
        <ul className="block-list">{s.topScorers.map((p) => <li key={p.id}>{p.name ?? playerName(replay, p.id)} <b>{p.goals}</b></li>)}</ul>
        <h4>{t(lang, 'se.records')}</h4>
        <ul className="block-list">
          {rec.fastestGoal && <li>{t(lang, 'se.fast')}: <b>{f1(rec.fastestGoal.minute, 1)} {t(lang, 'se.minute')}</b></li>}
          {rec.biggestWin.score && <li>{t(lang, 'se.big')}: <b>{shortOf(replay, rec.biggestWin.home!)} {rec.biggestWin.score[0]}–{rec.biggestWin.score[1]} {shortOf(replay, rec.biggestWin.away!)}</b></li>}
          {rec.highestScoring.score && <li>{t(lang, 'se.high')}: <b>{rec.highestScoring.score[0]}–{rec.highestScoring.score[1]}</b></li>}
        </ul>
        {tr && tr[home.id] && tr[away.id] && (
          <>
            <h4>{t(lang, 'se.style')}</h4>
            <Radar axes={tr[home.id].map((x) => x.key)} series={[home, away].map((c) => ({ color: colorOf(replay, c.id), label: c.short, values: tr[c.id].map((x) => x.scaled) }))} lang={lang} prefix="tax" />
          </>
        )}
      </section>
    </div>
  )
}

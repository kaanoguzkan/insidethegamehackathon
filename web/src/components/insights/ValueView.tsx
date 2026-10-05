import { t } from '../../i18n'
import { clockAt } from '../../lib/clock'
import { colorOf, Explain, f1, playerName, shortOf, type ViewProps } from './common'

const TYPE: Record<string, string> = { pass: 'pass', shot: 'shot', carry: 'carry', dribble: 'dribble', tackle: 'tackle', interception: 'interception', clearance: 'clearance', ball_recovery: 'recovery', block: 'block', save: 'save', claim: 'claim', foul: 'foul' }

export function ValueView({ replay, a, lang }: ViewProps) {
  const pv = a.possessionValue
  if (!pv.available) return <p className="muted">{t(lang, 'noAnalytics')}</p>
  const rows = a.players.filter((p) => p.value !== null).slice(0, 10)
  const top = a.playerOfTheMatch
  return (
    <div className="ins-grid">
      <section>
        <h3>{t(lang, 'val.title')}</h3>
        <Explain>{t(lang, 'val.explain')}</Explain>
        <ol className="best-actions">
          {(pv.best ?? []).slice(0, 8).map((x) => (
            <li key={x.id}>
              <span className="dot" style={{ background: colorOf(replay, x.team) }} />
              <b>{clockAt(replay.meta, x.ms).label}</b> {x.name ?? playerName(replay, x.player)} <span className="muted">{shortOf(replay, x.team)} · {TYPE[x.type] ?? x.type}</span>
              <span className="val pos">+{f1(x.value, 2)}</span>
            </li>
          ))}
        </ol>
      </section>
      <section>
        <h3>{t(lang, 'val.players')}</h3>
        <table className="ins-table">
          <thead>
            <tr><th>{t(lang, 'col.player')}</th><th>{t(lang, 'col.pos')}</th><th>{t(lang, 'val.value')}</th><th>{t(lang, 'val.attack')}</th><th>{t(lang, 'val.defence')}</th><th>{t(lang, 'col.goals')}</th><th>{t(lang, 'col.keyp')}</th></tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id} className={top?.id === p.id ? 'potm' : ''}>
                <th scope="row"><span className="dot" style={{ background: colorOf(replay, p.team) }} /> {p.name}{top?.id === p.id ? ` ★` : ''}</th>
                <td>{p.pos}</td>
                <td className="n">{f1(p.value, 2)}</td>
                <td className="n">{f1(p.valueAttacking, 2)}</td>
                <td className="n">{f1(p.valueDefending, 2)}</td>
                <td className="n">{p.goals}</td>
                <td className="n">{p.keyPasses}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {top && <p className="ins-explain">★ {t(lang, 'val.potm')}: <b>{top.name}</b></p>}
      </section>
    </div>
  )
}

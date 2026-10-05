import { t } from '../../i18n'
import { clubs, colorOf, Explain, f1, type ViewProps } from './common'

const ORDER: Record<string, string[]> = { corner: ['near', 'far', 'short', 'edge'], free_kick: ['direct', 'cross'], throw_in: ['long'], goal_kick: ['short', 'long'] }
const TITLE: Record<string, string> = { corner: 'dead.corners', free_kick: 'dead.free', throw_in: 'dead.long', goal_kick: 'dead.goalkick' }

export function DeadBallView({ replay, a, lang }: ViewProps) {
  return (
    <div className="ins-grid">
      {clubs(replay).map((team) => {
        const sp = a.setPieces.teams[team.id]
        if (!sp) return null
        return (
          <section key={team.id}>
            <h3><span className="dot" style={{ background: colorOf(replay, team.id) }} /> {team.short} <span className="muted">{t(lang, `dead.${sp.defence}`)} · {t(lang, 'dead.defence')}</span></h3>
            <table className="ins-table">
              <thead>
                <tr><th>{t(lang, 'dead.taken')}</th><th>{t(lang, 'dead.n')}</th><th>{t(lang, 'dead.shots')}</th><th>{t(lang, 'dead.xg')}</th><th>{t(lang, 'dead.first')}</th></tr>
              </thead>
              <tbody>
                {Object.keys(ORDER).flatMap((kind) =>
                  ORDER[kind].filter((r) => sp.taken[kind]?.[r]).map((r) => {
                    const s = sp.taken[kind][r]
                    const first = kind === 'goal_kick' ? sp.goalKickFirstPass[r] : undefined
                    return (
                      <tr key={`${kind}-${r}`}>
                        <th scope="row">{t(lang, TITLE[kind])} · {t(lang, `routine.${r}`)}</th>
                        <td className="n">{s.n}</td>
                        <td className="n">{kind === 'goal_kick' ? '–' : s.shots}</td>
                        <td className="n">{kind === 'goal_kick' ? '–' : f1(s.xg, 2)}</td>
                        <td className="n">{first && first.rate !== null ? `${Math.round(first.rate * 100)}%` : '–'}</td>
                      </tr>
                    )
                  }),
                )}
              </tbody>
            </table>
            {Object.keys(sp.conceded).length > 0 && (
              <>
                <h4>{t(lang, 'dead.conceded')}</h4>
                <ul className="block-list">
                  {Object.entries(sp.conceded).map(([defence, s]) => (
                    <li key={defence}><b>{t(lang, `dead.${defence}`)}</b> {s.n} · {t(lang, 'dead.shots')} {s.shots} · xG {f1(s.xg, 2)}</li>
                  ))}
                </ul>
              </>
            )}
          </section>
        )
      })}
      <Explain>{t(lang, 'tab.dead')}: {a.clubs.map((c) => replay.meta.home.id === c ? replay.meta.home.short : replay.meta.away.short).join(' · ')}</Explain>
    </div>
  )
}

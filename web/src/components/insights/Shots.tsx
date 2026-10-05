import { t } from '../../i18n'
import { clockAt, totalMs } from '../../lib/clock'
import { clubs, colorOf, f1, PitchSvg, playerName, shortOf, Versus, type ViewProps } from './common'

const W = 320
const H = 150

export function ShotsView({ replay, a, lang, ms }: ViewProps) {
  const total = totalMs(replay.meta)
  const [home, away] = clubs(replay)
  const race = a.shots.race
  const maxXg = Math.max(0.5, ...Object.values(race).map((s) => s[s.length - 1][1]))
  const x = (v: number) => 24 + (v / total) * (W - 32)
  const y = (v: number) => H - 18 - (v / maxXg) * (H - 30)
  const step = (club: string) =>
    race[club].map((p, i, arr) => (i ? `L${x(p[0]).toFixed(1)} ${y(arr[i - 1][1]).toFixed(1)} L${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}` : `M${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`)).join(' ')
  return (
    <div className="ins-grid">
      <section>
        <h3>{t(lang, 'sh.race')}</h3>
        <svg className="race" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t(lang, 'sh.race')}>
          {[0, 0.5, 1].map((g) => (
            <g key={g}>
              <line x1={24} x2={W - 8} y1={y(g * maxXg)} y2={y(g * maxXg)} className="wp-grid" />
              <text x={20} y={y(g * maxXg) + 3} className="axis" textAnchor="end">{(g * maxXg).toFixed(1)}</text>
            </g>
          ))}
          {[home.id, away.id].map((c) => (
            <g key={c}>
              <path d={step(c)} fill="none" stroke={colorOf(replay, c)} strokeWidth="2.4" />
              {race[c].filter((p, i, arr) => i > 0 && p[2] > arr[i - 1][2]).map((p) => (
                <circle key={p[0]} cx={x(p[0])} cy={y(p[1])} r="4.5" fill="#ffd24a" stroke="#0b1117" strokeWidth="1.5" />
              ))}
            </g>
          ))}
          <line x1={x(ms)} x2={x(ms)} y1={0} y2={H} className="tl-head" />
        </svg>
        <div className="versus-list">
          <Versus label={t(lang, 'sh.shots')} a={a.shots.teams[home.id].shots} b={a.shots.teams[away.id].shots} colorA={colorOf(replay, home.id)} colorB={colorOf(replay, away.id)} />
          <Versus label={t(lang, 'sh.ontarget')} a={a.shots.teams[home.id].onTarget} b={a.shots.teams[away.id].onTarget} colorA={colorOf(replay, home.id)} colorB={colorOf(replay, away.id)} />
          <Versus label={t(lang, 'sh.xg')} a={a.shots.teams[home.id].xg} b={a.shots.teams[away.id].xg} colorA={colorOf(replay, home.id)} colorB={colorOf(replay, away.id)} fmt={(v) => v.toFixed(2)} />
          <Versus label={t(lang, 'sh.xgot')} a={a.shots.teams[home.id].xgot} b={a.shots.teams[away.id].xgot} colorA={colorOf(replay, home.id)} colorB={colorOf(replay, away.id)} fmt={(v) => v.toFixed(2)} />
        </div>
      </section>
      <section>
        <h3>{t(lang, 'sh.map')}</h3>
        <div className="shotmaps">
          {[home, away].map((team) => (
            <figure key={team.id}>
              <figcaption>{team.short}</figcaption>
              <PitchSvg half label={`${t(lang, 'sh.map')}: ${team.short}`}>
                {a.shots.shots.filter((s) => s.team === team.id).map((s) => (
                  <circle key={s.id} cx={s.x} cy={s.y} r={0.9 + Math.sqrt(s.xg) * 4.2} className={s.outcome === 'goal' ? 'shot goal' : 'shot'} fill={s.outcome === 'goal' ? '#ffd24a' : colorOf(replay, team.id)} fillOpacity={s.outcome === 'goal' ? 0.95 : 0.55} stroke="#fff" strokeWidth="0.35">
                    <title>{`${clockAt(replay.meta, s.ms).label} ${playerName(replay, s.player)} · xG ${s.xg.toFixed(2)}${s.xgot !== null ? ` · xGOT ${s.xgot.toFixed(2)}` : ''} · ${s.outcome}`}</title>
                  </circle>
                ))}
              </PitchSvg>
            </figure>
          ))}
        </div>
        <p className="ins-explain">{t(lang, 'sh.legend')}</p>
        <h4>{t(lang, 'sh.gk')}</h4>
        <table className="ins-table">
          <thead>
            <tr><th>{t(lang, 'sh.gk')}</th><th>{t(lang, 'sh.saves')}</th><th>{t(lang, 'sh.faced')}</th><th>{t(lang, 'sh.prevented')}</th></tr>
          </thead>
          <tbody>
            {[home, away].map((team) => {
              const g = a.goalkeepers[team.id]
              return g ? (
                <tr key={team.id}>
                  <th scope="row">{g.name} <span className="muted">{shortOf(replay, team.id)}</span></th>
                  <td>{g.saves}/{g.onTarget}</td>
                  <td>{f1(g.xgotFaced, 2)}</td>
                  <td className={g.goalsPrevented >= 0 ? 'pos' : 'neg'}>{g.goalsPrevented >= 0 ? '+' : ''}{f1(g.goalsPrevented, 2)}</td>
                </tr>
              ) : null
            })}
          </tbody>
        </table>
      </section>
    </div>
  )
}

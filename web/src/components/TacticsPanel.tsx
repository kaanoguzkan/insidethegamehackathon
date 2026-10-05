import { t } from '../i18n'
import type { Replay } from '../lib/data'
import { CORNER_ORDER, formationAt, setPieceCounts, tagKeys, totalCorners } from '../lib/tactics'
import type { Lang, TeamMeta } from '../lib/types'
import { Crest } from './Crest'

function TeamTactics({ replay, team, ms, lang }: { replay: Replay; team: TeamMeta; ms: number; lang: Lang }) {
  const f = formationAt(replay, team, ms)
  const sp = setPieceCounts(replay.events, team.id, ms)
  const corners = CORNER_ORDER.filter((k) => sp.corners[k]).map((k) => `${t(lang, `corner.${k}`)} ${sp.corners[k]}`)
  const rows: [string, number, string][] = [
    [t(lang, 'corners'), totalCorners(sp), corners.join(' · ')],
    [t(lang, 'freeKicks'), sp.freeKicks.direct + sp.freeKicks.cross, `${t(lang, 'fkDirect')} ${sp.freeKicks.direct} · ${t(lang, 'fkCross')} ${sp.freeKicks.cross}`],
    [t(lang, 'goalKicks'), sp.goalKicks.short + sp.goalKicks.long, `${t(lang, 'gkShort')} ${sp.goalKicks.short} · ${t(lang, 'gkLong')} ${sp.goalKicks.long}`],
  ]
  if (sp.longThrows > 0) rows.push([t(lang, 'longThrows'), sp.longThrows, ''])
  return (
    <div className="tt">
      <div className="tt-head">
        <Crest team={team} size={22} />
        <b>{team.short}</b>
        <span className="formation">{f.name}</span>
        {f.changed && <em className="changed">{t(lang, 'changedShape')}</em>}
      </div>
      {(f.attack || f.block) && (
        <dl className="shapes">
          {f.attack && (<><dt>{t(lang, 'builds')}</dt><dd>{f.attack}</dd></>)}
          {f.block && (<><dt>{t(lang, 'defends')}</dt><dd>{f.block}</dd></>)}
        </dl>
      )}
      <ul className="tags">
        {tagKeys(team).map((k) => (
          <li key={k}>{t(lang, k)}</li>
        ))}
      </ul>
      <table className="sp" aria-label={`${t(lang, 'setPieces')}: ${team.short}`}>
        <tbody>
          {rows.map(([label, n, detail]) => (
            <tr key={label}>
              <th scope="row">{label}</th>
              <td className="n">{n}</td>
              <td className="d">{detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function TacticsPanel({ replay, ms, lang }: { replay: Replay; ms: number; lang: Lang }) {
  return (
    <section className="panel tactics">
      <h2 className="panel-title">{t(lang, 'tactics')}</h2>
      <TeamTactics replay={replay} team={replay.meta.home} ms={ms} lang={lang} />
      <TeamTactics replay={replay} team={replay.meta.away} ms={ms} lang={lang} />
      <p className="muted small">{t(lang, 'setPieces')}</p>
    </section>
  )
}

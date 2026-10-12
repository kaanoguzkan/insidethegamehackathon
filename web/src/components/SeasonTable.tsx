import { t } from '../i18n'
import type { Lang } from '../lib/types'
import type { Club, StandingRow } from '../lib/season'

/** The league table. `compact` drops the columns a small panel has no room for. */
export function SeasonTable({ rows, clubs, lang, compact = false, highlight = [] }: { rows: StandingRow[]; clubs: Record<string, Club>; lang: Lang; compact?: boolean; highlight?: string[] }) {
  return (
    <table className="season-table">
      <thead>
        <tr>
          <th aria-label="#" />
          <th className="left">{t(lang, 'season.col.club')}</th>
          <th title="played">{t(lang, 'season.col.p')}</th>
          {!compact && (
            <>
              <th>{t(lang, 'season.col.w')}</th>
              <th>{t(lang, 'season.col.d')}</th>
              <th>{t(lang, 'season.col.l')}</th>
              <th>{t(lang, 'season.col.gf')}</th>
              <th>{t(lang, 'season.col.ga')}</th>
            </>
          )}
          <th>{t(lang, 'season.col.gd')}</th>
          <th>{t(lang, 'season.col.pts')}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={r.club} className={highlight.includes(r.club) ? 'on' : ''}>
            <td className="muted">{i + 1}</td>
            <td className="left">
              <span className="season-dot" style={{ background: clubs[r.club]?.primary ?? '#888' }} aria-hidden="true" />
              {compact ? (clubs[r.club]?.short ?? r.name) : r.name}
            </td>
            <td>{r.played}</td>
            {!compact && (
              <>
                <td>{r.won}</td>
                <td>{r.drawn}</td>
                <td>{r.lost}</td>
                <td>{r.gf}</td>
                <td>{r.ga}</td>
              </>
            )}
            <td>{r.gd > 0 ? `+${r.gd}` : r.gd}</td>
            <td>
              <b>{r.points}</b>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

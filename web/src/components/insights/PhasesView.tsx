import { t } from '../../i18n'
import { PHASES, type Phase, type PhaseTeam, pct } from '../../lib/analytics'
import { totalMs } from '../../lib/clock'
import { formationAt } from '../../lib/tactics'
import type { TeamMeta } from '../../lib/types'
import { Crest } from '../Crest'
import { Explain, f1, type ViewProps } from './common'

const BUCKET_MS = 45_000

/** The phase the team spent most of each 45-second slice in, so the bar reads as stretches rather than seams. */
function dominantPhases(seg: [number, number][], total: number): number[] {
  const n = Math.ceil(total / BUCKET_MS)
  const spent = Array.from({ length: n }, () => PHASES.map(() => 0))
  seg.forEach(([start, idx], i) => {
    const stop = i + 1 < seg.length ? seg[i + 1][0] : total
    for (let t = start; t < stop; ) {
      const b = Math.min(n - 1, Math.floor(t / BUCKET_MS))
      const next = Math.min(stop, (b + 1) * BUCKET_MS)
      spent[b][idx] += next - t
      t = next
    }
  })
  return spent.map((row) => row.indexOf(Math.max(...row)))
}

/** One team's phases across the match: a coloured bar with the playhead on it. */
function Timeline({ ph, total, ms, label }: { ph: PhaseTeam; total: number; ms: number; label: string }) {
  const buckets = dominantPhases(ph.segments, total)
  const w = (BUCKET_MS / total) * 1000
  return (
    <svg className="ph-timeline" viewBox="0 0 1000 18" preserveAspectRatio="none" role="img" aria-label={label}>
      {buckets.map((idx, i) => (
        <rect key={i} x={i * w} y={0} width={w + 0.4} height={18} className={`ph-fill ph-${PHASES[idx]}`} />
      ))}
      <line x1={(ms / total) * 1000} x2={(ms / total) * 1000} y1={0} y2={18} className="tl-head" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

function TeamPhases({ team, ph, total, ms, lang, replay }: { team: TeamMeta; ph: PhaseTeam; total: number; ms: number; lang: ViewProps['lang']; replay: ViewProps['replay'] }) {
  const f = formationAt(replay, team, ms)
  const top = PHASES.reduce((a, b) => (ph.share[b] > ph.share[a] ? b : a))
  return (
    <section className="ph-team">
      <header className="tt-head">
        <Crest team={team} size={22} />
        <b>{team.short}</b>
        <span className="formation">{team.startFormation ?? team.formation}</span>
      </header>
      <Timeline ph={ph} total={total} ms={ms} label={`${team.short}: ${t(lang, 'tab.phases')}`} />
      <ul className="ph-legend">
        {PHASES.map((p) => (
          <li key={p}><i className={`ph-dot ph-${p}`} aria-hidden="true" />{t(lang, `phase.${p}`)}</li>
        ))}
      </ul>
      <p className="ins-explain">{t(lang, 'ph.mostly')} <b>{t(lang, `phase.${top}`)}</b> ({pct(ph.share[top])}).{f.rest ? ` ${t(lang, 'ph.rest')}: ${f.rest}.` : ''}</p>
      <table className="ins-table compact">
        <thead>
          <tr>
            <th /><th className="n">{t(lang, 'ph.share')}</th><th className="n">{t(lang, 'ph.entries')}</th>
            <th className="n">{t(lang, 'ph.line')}</th><th className="n">{t(lang, 'ph.length')}</th><th className="n">{t(lang, 'ph.width')}</th><th>{t(lang, 'ph.trigger')}</th>
          </tr>
        </thead>
        <tbody>
          {PHASES.map((p: Phase) => {
            const m = ph.measured[p]
            const causes = Object.entries(ph.causes[p] ?? {}).sort((a, b) => b[1] - a[1])
            return (
              <tr key={p}>
                <th scope="row" title={t(lang, `phase.${p}.d`)}><i className={`ph-dot ph-${p}`} aria-hidden="true" />{t(lang, `phase.${p}`)}</th>
                <td className="n">{pct(ph.share[p])}</td>
                <td className="n">{ph.entries[p]}</td>
                <td className="n">{m ? f1(m.lineHeightM, 0) : '–'}</td>
                <td className="n">{m ? f1(m.lengthM, 0) : '–'}</td>
                <td className="n">{m ? f1(m.widthM, 0) : '–'}</td>
                <td>{causes.length ? t(lang, `cause.${causes[0][0]}`) : '–'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </section>
  )
}

export function PhasesView({ replay, a, lang, ms }: ViewProps) {
  const total = totalMs(replay.meta)
  const teams = [replay.meta.home, replay.meta.away]
  if (!a.phases) return <p className="muted">{t(lang, 'noAnalytics')}</p>
  return (
    <div>
      <h3>{t(lang, 'ph.title')}</h3>
      <Explain>{t(lang, 'ph.explain')}</Explain>
      <div className="ins-grid">
        {teams.map((team) => a.phases![team.id] && <TeamPhases key={team.id} team={team} ph={a.phases![team.id]} total={total} ms={ms} lang={lang} replay={replay} />)}
      </div>
      <p className="ins-explain">{t(lang, 'ph.measured')}</p>
    </div>
  )
}

import { metricLabel, momentTypeLabel, t } from '../i18n'
import type { LiveBrain } from '../hooks/useLiveBrain'
import type { Replay } from '../lib/data'
import type { Lang, MetricChange, Moment } from '../lib/types'

interface Props {
  moment: Moment | null
  replay: Replay
  lang: Lang
  onClose: () => void
  onSeek: (ms: number) => void
  showOnPitch: boolean
  setShowOnPitch: (v: boolean) => void
  health?: string
  live?: LiveBrain
}

const AGENT_ICON: Record<string, string> = { editor: 'E', explainer: 'X', verifier: '✓', storyteller: 'S', localizer: 'L', producer: 'P', template: 'T', interpreter: 'I', router: 'R', cache: '⚡', composer: 'C', repairer: '+' }

function fmt(v: number | null | undefined): string {
  return v === null || v === undefined ? '–' : String(v)
}

export function EvidenceDrawer({ moment, replay, lang, onClose, onSeek, showOnPitch, setShowOnPitch, health = 'healthy', live }: Props) {
  if (!moment) return null
  const short = (id: string) => (id === replay.meta.home.id ? replay.meta.home.short : id === replay.meta.away.id ? replay.meta.away.short : id)
  const rows = Object.entries(moment.metrics).filter(([, m]) => m.before !== undefined || m.value !== undefined)
  const ex = moment.explanations?.[lang] ?? moment.explanation
  const events = moment.eventIds.map((id) => replay.eventsById.get(id)).filter((e): e is NonNullable<typeof e> => !!e)
  const run = health !== 'healthy' ? moment.variants?.[health] : undefined
  const level = run?.level ?? moment.level ?? 0
  const trace = run?.trace ?? moment.trace
  return (
    <aside className="drawer" role="dialog" aria-modal="false" aria-label={t(lang, 'evidence')}>
      <header>
        <div>
          <small>{moment.detectedAt.label} · {t(lang, 'evidence')}</small>
          <h2>{momentTypeLabel(lang, moment.type)}{moment.subjectTeam ? ` · ${short(moment.subjectTeam)}` : ''}</h2>
        </div>
        <button type="button" className="icon" onClick={onClose} aria-label={t(lang, 'close')}>×</button>
      </header>

      <div className="drawer-body">
        {live?.available && <LiveSection live={live} momentId={moment.id} lang={lang} />}
        {ex && (
          <section>
            <h3>{t(lang, 'explanation')} <span className={`conf conf-${ex.confidence}`}>{t(lang, 'confidence')}: {ex.confidence}</span></h3>
            <dl className="explain">
              <dt>{t(lang, 'what')}</dt><dd>{ex.what}</dd>
              <dt>{t(lang, 'whyLabel')}</dt><dd>{ex.why}</dd>
              {ex.so_what && (<><dt>{t(lang, 'soWhat')}</dt><dd>{ex.so_what}</dd></>)}
            </dl>
            {ex.caveats.length > 0 && (
              <div className="caveat"><b>{t(lang, 'caveats')}</b><ul>{ex.caveats.map((c) => <li key={c}>{c}</li>)}</ul></div>
            )}
          </section>
        )}

        {rows.length > 0 && (
          <section>
            <h3>{t(lang, 'metrics')}</h3>
            {Object.keys(moment.windows).length > 0 && (
              <p className="windows">
                {t(lang, 'before')}: {moment.windows.before?.label} → {t(lang, 'after')}: {moment.windows.after?.label}
              </p>
            )}
            <table className="metrics">
              <thead><tr><th scope="col"></th><th scope="col">{t(lang, 'before')}</th><th scope="col">{t(lang, 'after')}</th><th scope="col">{t(lang, 'change')}</th><th scope="col"><span className="sr-only">consistency</span></th></tr></thead>
              <tbody>
                {rows.map(([key, m]) => <MetricRow key={key} k={key} m={m} lang={lang} short={short} glossary={moment.glossary} />)}
              </tbody>
            </table>
            <p className="legend"><span className="ok">✓</span> {t(lang, 'supports')} · <span className="no">✗</span> {t(lang, 'against')}</p>
          </section>
        )}

        <section>
          <h3>{t(lang, 'trace')}</h3>
          <p className={`level level-${level}`}>{t(lang, `level${Math.min(level, 3)}`)}</p>
          <ol className="trace">
            {trace.map((s, i) => (
              <li key={i}>
                <span className="agent" title={s.agent}>{AGENT_ICON[s.agent] ?? '•'}</span>
                <b>{s.agent}</b> <span>{s.outcome}</span>
                {s.issues?.map((x) => <em key={x} className="issue">{x}</em>)}
              </li>
            ))}
          </ol>
        </section>

        <section>
          <h3>{t(lang, 'evidence')}</h3>
          <button type="button" className="btn" onClick={() => setShowOnPitch(!showOnPitch)} aria-pressed={showOnPitch}>
            {showOnPitch ? t(lang, 'hideOnPitch') : t(lang, 'showOnPitch')}
          </button>
          <ol className="events">
            {events.map((e, i) => (
              <li key={e.id}>
                <button type="button" onClick={() => onSeek(Math.max(0, e.clock.matchMs - 4000))}>
                  <span className="n">{i + 1}</span>
                  {e.type}{e.kind ? ` · ${e.kind}` : ''}{e.outcome ? ` · ${e.outcome}` : ''}
                  <small>{e.team ? short(e.team) : ''}</small>
                </button>
              </li>
            ))}
          </ol>
          {moment.players.length > 0 && <p className="players">{moment.players.map((p) => `${p.name} (${short(p.team)})`).join(', ')}</p>}
        </section>
      </div>
    </aside>
  )
}

function MetricRow({ k, m, lang, short, glossary }: { k: string; m: MetricChange; lang: Lang; short: (id: string) => string; glossary: Record<string, string> }) {
  const [club, base] = k.split('.')
  const who = club === 'match' ? '' : `${short(club)} · `
  const delta = m.delta
  return (
    <tr title={glossary[base]}>
      <th scope="row">{who}{metricLabel(lang, base)}</th>
      {m.before !== undefined ? (
        <>
          <td>{fmt(m.before)}</td>
          <td><b>{fmt(m.after)}</b></td>
          <td className={delta && delta > 0 ? 'up' : delta && delta < 0 ? 'down' : ''}>
            {delta !== undefined ? `${delta > 0 ? '+' : ''}${delta}` : ''}{m.changePct !== undefined ? ` (${m.changePct > 0 ? '+' : ''}${m.changePct}%)` : ''}
          </td>
        </>
      ) : (
        <td colSpan={3}><b>{fmt(m.value)}</b></td>
      )}
      <td>{m.consistent === true ? <span className="ok" aria-label={t(lang, 'supports')}>✓</span> : m.consistent === false ? <span className="no" aria-label={t(lang, 'against')}>✗</span> : null}</td>
    </tr>
  )
}

function LiveSection({ live, momentId, lang }: { live: LiveBrain; momentId: string; lang: Lang }) {
  const res = live.resultFor(momentId)
  let body: JSX.Element | null = null
  if (!live.enabled) {
    body = (
      <>
        <p className="hint">{t(lang, 'liveOffHint')}</p>
        <button type="button" className="btn live" aria-pressed={false} onClick={live.toggle}>{t(lang, 'liveTurnOn')}</button>
      </>
    )
  }
  else if (live.status === 'waking') body = <p role="status">{t(lang, 'liveWaking')}</p>
  else if (live.status === 'down') body = <p className="caveat">{t(lang, 'liveDown')}</p>
  else if (live.busy && !res) body = <p role="status">{t(lang, 'liveAsking')}</p>
  else if (live.error && !res) body = <p className="caveat">{t(lang, 'liveFailed')}</p>
  else if (res) {
    const stories = res.overlays.filter((o) => o.kind === 'lower_third')
    body = (
      <>
        {stories.map((o) => {
          const model = o.provenance.fallbackLevel < 2
          return (
            <article key={o.id} className="live-story">
              <small>{t(lang, o.cohort.mode === 'any' ? 'casual' : o.cohort.mode)} · {o.cohort.language.toUpperCase()}</small>
              {model ? (
                <>
                  <h4>{o.content.headline}</h4>
                  <p>{o.content.body}</p>
                </>
              ) : (
                <p className="hint">{t(lang, 'liveTemplate')}</p>
              )}
              <p className="live-who">
                {o.provenance.agents.map((a, i) => <span key={i} className="agent" title={a}>{AGENT_ICON[a] ?? '•'}</span>)}
                <span>{model ? t(lang, 'liveWrote') : t(lang, 'byTemplate')} · {(res.elapsedMs / 1000).toFixed(1)}{t(lang, 'liveSeconds')}{o.provenance.agents.includes('cache') ? ` · ${t(lang, 'liveFromCache')}` : ''}</span>
              </p>
            </article>
          )
        })}
      </>
    )
  }
  return (
    <section className="live-ai">
      <h3>{t(lang, 'liveAI')}</h3>
      {body}
    </section>
  )
}

import { useEffect, useMemo, useState } from 'react'
import { useLiveFeed } from '../hooks/useLiveFeed'
import { momentTypeLabel, t } from '../i18n'
import { BRAIN_URL, brainConfigured, wakeBrain } from '../lib/brain'
import { SAFE_ID } from '../lib/data'
import {
  clockLabel, listLive, liveClock, LiveBusy, type LiveEvent, type LiveMatch, type LiveOverlay, median, pipelineDelays, scoreOf, startLive, writer,
} from '../lib/live'
import type { Lang, Mode } from '../lib/types'
import { LoadBar } from './LoadBar'

const SCENARIOS = ['red-card-drama', 'pressing-collapse', 'high-line-gamble']
const STARTS: { minute: number; key: string }[] = [
  { minute: 0, key: 'live.fromKick' },
  { minute: 40, key: 'live.fromMinute' },
  { minute: 55, key: 'live.fromMinute' },
]
const SHOWN_KINDS = new Set(['lower_third', 'ticker', 'fact_card', 'stat_card'])

interface Props {
  lang: Lang
  mode: Mode
  matchId: string | null
  onMatch: (id: string | null) => void
  onProfile: (p: { language?: Lang; mode?: Mode }) => void
}

export function LivePage({ lang, mode, matchId, onMatch, onProfile }: Props) {
  const [list, setList] = useState<LiveMatch[] | null>(null)
  const [scenario, setScenario] = useState(SCENARIOS[0])
  const [from, setFrom] = useState(0)
  const [starting, setStarting] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [waking, setWaking] = useState(brainConfigured)

  // Wake the Brain (it scales to zero), then keep the list of live matches fresh.
  useEffect(() => {
    if (!brainConfigured) return
    const ctl = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = async () => {
      try {
        setList(await listLive(BRAIN_URL, AbortSignal.any([ctl.signal, AbortSignal.timeout(60_000)])))
        setWaking(false)
      } catch {
        /* still waking */
      }
      if (!ctl.signal.aborted) timer = setTimeout(load, 5000)
    }
    void wakeBrain(BRAIN_URL, ctl.signal).then(() => !ctl.signal.aborted && void load())
    return () => {
      ctl.abort()
      if (timer) clearTimeout(timer)
    }
  }, [])

  // A match id from the URL has to look like one before it reaches a request.
  const id = matchId && SAFE_ID.test(matchId) ? matchId : null
  const live = useLiveFeed(id)
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!id) return
    const timer = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(timer)
  }, [id])

  const start = async () => {
    setStarting(true)
    setNote(null)
    try {
      const r = await startLive(scenario, from)
      onMatch(r.matchId)
    } catch (e) {
      if (e instanceof LiveBusy) {
        setNote(t(lang, 'live.busy'))
        onMatch(e.matchId)
      } else setNote(t(lang, (e as Error).message === 'rate' ? 'live.rate' : 'live.failed'))
    } finally {
      setStarting(false)
    }
  }

  if (!brainConfigured) {
    return (
      <main className="live">
        <Head lang={lang} />
        <p className="caveat">{t(lang, 'live.nobrain')}</p>
      </main>
    )
  }

  const m = live.match
  const clock = m ? liveClock(m, live.receivedAt, now) : 0
  const [hs, as] = scoreOf(live.events, m?.home?.id, m?.away?.id)
  const stories = live.overlays.filter((o) => o.kind === 'lower_third')
  const writers = { model: 0, mended: 0, template: 0 }
  for (const o of stories.filter((x) => x.cohort.language === lang && x.cohort.mode === mode && x.cohort.perspective === 'neutral')) writers[writer(o)]++
  const delay = median(m ? pipelineDelays(m, live.moments, live.overlays) : [])
  const due = useMemo(
    () => dueOverlays(live.overlays, lang, mode, clock),
    // The clock moves every tick, the list only when a new overlay becomes due: key on the count it would show.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [live.overlays, lang, mode, Math.floor(clock / 5000)],
  )

  return (
    <main className="live">
      <Head lang={lang} />

      <section className="live-card" aria-label={t(lang, 'live.start')}>
        <div className="live-controls">
          <label>
            {t(lang, 'live.scenario')}
            <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
              {SCENARIOS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label>
            {t(lang, 'live.from')}
            <select value={from} onChange={(e) => setFrom(Number(e.target.value))}>
              {STARTS.map((s) => <option key={s.minute} value={s.minute}>{s.minute === 0 ? t(lang, s.key) : `${t(lang, s.key)} ${s.minute}`}</option>)}
            </select>
          </label>
          <button type="button" className="btn live-start" disabled={starting || waking} onClick={start}>{t(lang, 'live.start')}</button>
          <span className="live-lang">
            {(['en', 'es', 'tr'] as const).map((l) => <button key={l} type="button" className={`chip${l === lang ? ' on' : ''}`} aria-pressed={l === lang} onClick={() => onProfile({ language: l })}>{l.toUpperCase()}</button>)}
            {(['casual', 'analyst'] as const).map((x) => <button key={x} type="button" className={`chip${x === mode ? ' on' : ''}`} aria-pressed={x === mode} onClick={() => onProfile({ mode: x })}>{t(lang, x)}</button>)}
          </span>
        </div>
        {waking && <><p role="status" className="hint">{t(lang, 'live.waking')}</p><LoadBar seconds={25} /></>}
        {starting && <><p role="status" className="hint">{t(lang, 'live.starting')}</p><LoadBar seconds={40} /></>}
        {note && <p role="status" className="hint">{note}</p>}
        {list && !waking && (
          <div className="live-recent">
            <strong>{t(lang, 'live.join')}</strong>
            {list.length === 0 && <span className="muted"> {t(lang, 'live.none')}</span>}
            <ul>
              {list.slice(0, 5).map((r) => (
                <li key={r.matchId}>
                  <button type="button" className={`btn${r.matchId === id ? ' on' : ''}`} aria-pressed={r.matchId === id} onClick={() => onMatch(r.matchId)}>
                    {r.home && r.away ? `${r.home.short} v ${r.away.short}` : r.matchId} · {t(lang, `live.status.${r.status ?? 'scheduled'}`)}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {id && (
        <>
          <section className="live-card live-board" aria-live="polite">
            {m?.home && m.away ? (
              <>
                <div className="live-score"><span>{m.home.name}</span><b>{hs} – {as}</b><span>{m.away.name}</span></div>
                <div className="live-meta">
                  <span className={`live-status ${m.status}`}>{t(lang, `live.status.${m.status ?? 'scheduled'}`)}</span>
                  <span className="live-clock">{clockLabel(clock)}</span>
                  {m.speed ? <span className="muted">{m.speed}× {t(lang, 'live.speed')}</span> : null}
                </div>
              </>
            ) : (
              <><p role="status" className="hint">{t(lang, 'live.starting')}</p><LoadBar seconds={40} /></>
            )}
            {live.error && <p className="caveat">{t(lang, 'live.error')}</p>}
          </section>

          <section className="live-card" aria-label={t(lang, 'live.stages')}>
            <h2>{t(lang, 'live.stages')}</h2>
            <ol className="live-stages">
              <Stage name={t(lang, 'live.stage.feed')} value={String(live.events.length ? live.events[live.events.length - 1].n : 0)} note={t(lang, 'live.stage.feed.d')} />
              <Stage name={t(lang, 'live.stage.interpret')} value={String(live.moments.length)} note={t(lang, 'live.stage.interpret.d')} />
              <Stage name={t(lang, 'live.stage.agents')} value={String(writers.model + writers.mended + writers.template)} note={`${writers.model} / ${writers.mended} / ${writers.template} ${t(lang, 'live.writers')}`} />
              <Stage name={t(lang, 'live.stage.delay')} value={delay === null ? '–' : `${delay.toFixed(1)} ${t(lang, 'live.seconds')}`} note={t(lang, 'live.stage.delay.d')} />
            </ol>
          </section>

          <div className="live-cols">
            <section className="live-card" aria-label={t(lang, 'live.onscreen')}>
              <h2>{t(lang, 'live.onscreen')}</h2>
              {due.length === 0 && <p className="muted">{t(lang, 'live.onscreen.empty')}</p>}
              <ul className="live-overlays">
                {due.map((o) => (
                  <li key={o.id} className={`live-ov ${o.kind}`}>
                    <div className="live-ov-head"><b>{o.content.headline}</b><span className={`live-w ${writer(o)}`}>{t(lang, `live.${writer(o)}`)}{o.provenance.verified ? ` · ${t(lang, 'live.verified')}` : ''}</span></div>
                    {o.content.body && <p>{o.content.body}</p>}
                  </li>
                ))}
              </ul>
            </section>
            <section className="live-card">
              <h2>{t(lang, 'live.events')}</h2>
              {live.events.length === 0 && <p className="muted">{t(lang, 'live.empty')}</p>}
              <ul className="live-events">
                {[...live.events].filter((e) => e.clock.matchMs <= clock).slice(-12).reverse().map((e) => <li key={e.n}>{eventLine(e, m)}</li>)}
              </ul>
              <h2>{t(lang, 'live.moments')}</h2>
              {live.moments.length === 0 && <p className="muted">{t(lang, 'live.empty')}</p>}
              <ul className="live-moments">
                {[...live.moments].reverse().slice(0, 10).map((mo) => (
                  <li key={mo.id}><span className="muted">{Math.floor(mo.detectedAt.matchMs / 60000)}′</span> {momentTypeLabel(lang, mo.type)} <span className="muted">{mo.salience.toFixed(2)}</span></li>
                ))}
              </ul>
            </section>
          </div>
        </>
      )}

      <details className="live-about">
        <summary>{t(lang, 'live.about')}</summary>
        <p>{t(lang, 'live.about.body')}</p>
      </details>
    </main>
  )
}

function Head({ lang }: { lang: Lang }) {
  return (
    <header className="live-head">
      <a className="btn" href="#/">{t(lang, 'live.back')}</a>
      <h1>{t(lang, 'live.title')}</h1>
      <p>{t(lang, 'live.intro')}</p>
    </header>
  )
}

function Stage({ name, value, note }: { name: string; value: string; note: string }) {
  return (
    <li className="live-stage">
      <span className="live-stage-name">{name}</span>
      <b className="live-stage-value">{value}</b>
      <span className="muted">{note}</span>
    </li>
  )
}

/** The overlays of this viewer type whose time has come, newest first. */
export function dueOverlays(overlays: LiveOverlay[], lang: Lang, mode: Mode, clockMs: number): LiveOverlay[] {
  return overlays
    .filter((o) => SHOWN_KINDS.has(o.kind) && o.cohort.language === lang && (o.cohort.mode === mode || o.cohort.mode === 'any') && o.cohort.perspective === 'neutral' && o.displayAt.matchMs <= clockMs && (o.content.headline || o.content.body))
    .sort((a, b) => b.displayAt.matchMs - a.displayAt.matchMs || a.priority - b.priority)
    .slice(0, 8)
}

function eventLine(e: LiveEvent, m: LiveMatch | null): string {
  const who = e.player && m?.players?.[e.player] ? m.players[e.player] : ''
  const club = e.team === m?.home?.id ? m?.home?.short : e.team === m?.away?.id ? m?.away?.short : e.team
  return `${e.clock.minute}′ ${e.type.replace('_', ' ')}${who ? ` · ${who}` : ''}${club ? ` (${club})` : ''}${e.outcome && e.type === 'shot' ? ` · ${e.outcome}` : ''}`
}

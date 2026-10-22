import { useEffect, useMemo, useState } from 'react'
import { useLiveFeed } from '../hooks/useLiveFeed'
import { useLivePush } from '../hooks/useLivePush'
import { momentTypeLabel, t } from '../i18n'
import { BRAIN_URL, brainConfigured, wakeBrain } from '../lib/brain'
import { clockLabel, getConfig, LiveBusy, type LiveConfig, liveClock, median, pipelineDelays, scoreOf, stageDelays, startLive, writer } from '../lib/live'
import { listStreamDemos } from '../lib/stream'

const DEMOS_FALLBACK = ['red-card-drama', 'pressing-collapse', 'eight-goal-thriller']

/** The Azure services a match passes through, in order, with what each one has produced for this match so far. */
const FLOW = [
  ['Container Apps Job', 'plays the match'],
  ['Cosmos DB + Blob Storage', 'events, tracking chunks'],
  ['Event Grid → Functions', 'analyse, detect moments'],
  ['Brain + Foundry agents', 'write and verify the story'],
  ['Cosmos change feed → SignalR', 'push to this page'],
] as const

/**
 * The event-driven path, run for real: start a match as a Container Apps Job and watch its events, moments and verified stories arrive through the
 * Functions, the Brain and Azure SignalR. The match center plays the same engine in-process for speed; this page shows the cloud-native chain.
 */
export function PipelinePage({ lang = 'en' as const }) {
  const [config, setConfig] = useState<LiveConfig>({ push: null, delayS: 25 })
  const [demos, setDemos] = useState<string[]>(DEMOS_FALLBACK)
  const [id, setId] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    if (!brainConfigured) return
    const ctl = new AbortController()
    void wakeBrain(BRAIN_URL, ctl.signal).then(() => {
      void getConfig(BRAIN_URL, ctl.signal).then(setConfig).catch(() => undefined)
      void listStreamDemos(BRAIN_URL, ctl.signal).then((r) => r.demos.length && setDemos(r.demos.map((d) => d.id))).catch(() => undefined)
    })
    return () => ctl.abort()
  }, [])
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(timer)
  }, [])

  const [pollMs, setPollMs] = useState(1200)
  const live = useLiveFeed(id, pollMs)
  const push = useLivePush(id, config.push, live.inject)
  useEffect(() => setPollMs(push === 'live' ? 10_000 : 1200), [push])

  const start = async (demo: string) => {
    setNote(null)
    try {
      setId((await startLive(demo, 0)).matchId)
    } catch (e) {
      if (e instanceof LiveBusy) {
        setId(e.matchId)
        setNote('A match is already running in the pipeline, so you are following it.')
      } else setNote(e instanceof Error && e.message === 'rate' ? 'Too many starts in a minute. Try again shortly.' : 'The simulator job could not be started.')
    }
  }

  const m = live.match
  const liveMs = m ? liveClock(m, live.receivedAt, now) : 0
  const [hs, as] = scoreOf(live.events, m?.home?.id, m?.away?.id)
  const stories = live.overlays.filter((o) => o.kind === 'lower_third' && o.cohort.perspective === 'neutral' && o.cohort.language === lang)
  const writers = { model: 0, mended: 0, template: 0 }
  for (const o of stories) writers[writer(o)]++
  const delay = m ? median(pipelineDelays(m, live.moments, live.overlays)) : null
  const stages = m ? stageDelays(m, live.moments, live.overlays) : { interpret: [], write: [] }
  const counts = [
    m ? t(lang, `live.status.${m.status ?? 'scheduled'}`) : '–',
    `${live.events.length} events`,
    `${live.moments.length} moments`,
    `${stories.length} stories`,
    push === 'live' ? 'connected' : push === 'connecting' ? 'connecting…' : 'polling',
  ]
  const recent = useMemo(() => [...stories].sort((a, b) => b.displayAt.matchMs - a.displayAt.matchMs).slice(0, 6), [stories])

  return (
    <main className="live-page ops">
      <header>
        <a href="#" className="btn">← Match center</a>
        <h1>Cloud pipeline</h1>
        <p className="muted">
          The same match, played as a Container Apps Job and carried by events through Azure. Start one and watch it move from stage to stage. The match center plays the engine in-process for speed; this is the event-driven path.
        </p>
      </header>
      {!brainConfigured && <p>This build has no Brain to ask.</p>}
      <div className="ops-grid">
        {demos.map((d) => <button key={d} type="button" className="btn" disabled={!brainConfigured} onClick={() => void start(d)}>Run {d.replace(/-/g, ' ')}</button>)}
      </div>
      {note && <p role="status" className="hint">{note}</p>}
      {live.error && <p role="alert">The Brain did not answer. It may be waking up.</p>}
      {id && (
        <>
          <section className="live-card" aria-live="polite">
            {m?.home && m.away ? (
              <div className="live-score"><span>{m.home.name}</span><b>{hs} – {as}</b><span>{m.away.name}</span> <span className="muted">{clockLabel(liveMs)} · {m.speed}×</span></div>
            ) : (
              <p role="status" className="hint">Starting the job… a Container Apps Job takes about 20 seconds to start.</p>
            )}
          </section>
          <section className="live-card">
            <h2>Where the match is</h2>
            <ol className="live-stages">
              {FLOW.map(([name, what], i) => (
                <li className="live-stage" key={name}>
                  <span className="live-stage-name">{name}</span>
                  <b className="live-stage-value">{counts[i]}</b>
                  <span className="muted">{what}</span>
                </li>
              ))}
            </ol>
            <p className="muted">
              Moment to story: {delay === null ? '–' : `${delay.toFixed(1)} s`}
              {median(stages.interpret) !== null && median(stages.write) !== null ? ` (detect ${median(stages.interpret)!.toFixed(1)} s + write ${median(stages.write)!.toFixed(1)} s)` : ''}
              {' · '}stories written by the model / repaired / template: {writers.model} / {writers.mended} / {writers.template}
            </p>
          </section>
          <section className="live-card">
            <h2>Latest stories</h2>
            {recent.length === 0 && <p className="muted">Nothing yet.</p>}
            <ul className="live-overlays">
              {recent.map((o) => (
                <li key={o.id} className="live-ov">
                  <div className="live-ov-head"><b>{o.content.headline}</b><span className={`live-w ${writer(o)}`}>{t(lang, `live.${writer(o)}`)}{o.provenance.verified ? ` · ${t(lang, 'live.verified')}` : ''}</span></div>
                  {o.content.body && <p>{o.content.body}</p>}
                </li>
              ))}
            </ul>
            <ul className="live-moments">
              {[...live.moments].reverse().slice(0, 6).map((mo) => <li key={mo.id}><span className="muted">{Math.floor(mo.detectedAt.matchMs / 60000)}′</span> {momentTypeLabel(lang, mo.type)}</li>)}
            </ul>
          </section>
        </>
      )}
    </main>
  )
}

import { useEffect, useMemo, useRef, useState } from 'react'
import { useLiveFeed } from '../hooks/useLiveFeed'
import { useLivePush } from '../hooks/useLivePush'
import { useLiveTracking } from '../hooks/useLiveTracking'
import { momentTypeLabel, t } from '../i18n'
import { BRAIN_URL, brainConfigured, wakeBrain } from '../lib/brain'
import { SAFE_ID } from '../lib/data'
import {
  clockLabel, getConfig, getMeta, liveClock, type LiveConfig, type LiveEvent, type LiveMatch, type LiveOverlay, liveReplay, median, pipelineDelays, playClock, scoreOf,
  stageDelays, writer,
} from '../lib/live'
import { type ChannelNow, getSeason, SeasonWait, type SeasonView, tune } from '../lib/season'
import type { Meta, Profile } from '../lib/types'
import type { Cam } from '../lib/webgl'
import { LoadBar } from './LoadBar'
import { Screen } from './Screen'
import { SeasonTable } from './SeasonTable'

const SHOWN_KINDS = new Set(['lower_third', 'ticker', 'fact_card', 'stat_card'])
const DEFAULT_CONFIG: LiveConfig = { push: null, delayS: 25 }
const INTERMISSION_S = 10 // between full time and the next fixture

interface Props {
  profile: Profile
  /** A live match named in the URL (a shared link); without it the page tunes in to whatever is on. */
  matchId: string | null
  onMatch: (id: string | null) => void
  onProfile: (p: Partial<Profile>) => void
}

/** The home page: a match is already on when you arrive. */
export function LivePage({ profile, matchId, onMatch, onProfile }: Props) {
  const lang = profile.language
  const mode = profile.mode
  const [config, setConfig] = useState<LiveConfig>(DEFAULT_CONFIG)
  const [cam, setCam] = useState<Cam>('bc')
  const [tuned, setTuned] = useState<ChannelNow | null>(null)
  const [season, setSeason] = useState<SeasonView | null>(null)
  const [retune, setRetune] = useState(0) // bumped to tune in again (next match, full time)

  const named = matchId && SAFE_ID.test(matchId) ? matchId : null
  const id = named ?? tuned?.matchId ?? null

  // Tune in: wake the Brain (it sleeps when idle), then join the match that is on or start the next fixture. While the season is still being simulated, say so and try again.
  useEffect(() => {
    if (!brainConfigured || named) return
    const ctl = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    const attempt = async () => {
      try {
        setTuned(await tune({}, BRAIN_URL, AbortSignal.any([ctl.signal, AbortSignal.timeout(60_000)])))
        return
      } catch (e) {
        if (e instanceof SeasonWait) void getSeason(BRAIN_URL, ctl.signal).then(setSeason).catch(() => undefined)
      }
      if (!ctl.signal.aborted) timer = setTimeout(attempt, 3000)
    }
    void wakeBrain(BRAIN_URL, ctl.signal).then(() => {
      if (ctl.signal.aborted) return
      void getConfig(BRAIN_URL, ctl.signal).then(setConfig).catch(() => undefined)
      void attempt()
    })
    return () => {
      ctl.abort()
      if (timer) clearTimeout(timer)
    }
  }, [named, retune])

  // The table, kept fresh.
  useEffect(() => {
    if (!brainConfigured) return
    const ctl = new AbortController()
    const load = () => void getSeason(BRAIN_URL, ctl.signal).then(setSeason).catch(() => undefined)
    load()
    const timer = setInterval(load, 12_000)
    return () => {
      ctl.abort()
      clearInterval(timer)
    }
  }, [tuned?.matchId])

  const [pollMs, setPollMs] = useState(1200)
  const live = useLiveFeed(id, pollMs)
  const push = useLivePush(id, config.push, live.inject)
  useEffect(() => setPollMs(push === 'live' ? 10_000 : 1200), [push]) // pushes carry the news; the poll only reconciles

  const m = live.match
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!id) return
    const timer = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(timer)
  }, [id])
  const liveMs = m ? liveClock(m, live.receivedAt, now) : 0
  const playMs = playClock(liveMs, m?.speed, config.delayS)
  const fullTime = !!m && m.status === 'finished' && playMs >= (m.durationMs ?? Infinity) - 1000

  // At full time the next fixture goes on air after a short break (everyone who is watching asks; the first one starts it, the others join).
  const [countdown, setCountdown] = useState(INTERMISSION_S)
  useEffect(() => {
    if (!fullTime || named) return setCountdown(INTERMISSION_S)
    const timer = setInterval(() => setCountdown((c) => c - 1), 1000)
    return () => clearInterval(timer)
  }, [fullTime, named])
  useEffect(() => {
    if (fullTime && !named && countdown <= 0) {
      setCountdown(INTERMISSION_S)
      void tune({}).then(setTuned).catch(() => undefined)
    }
  }, [fullTime, named, countdown])

  // The pitch reads the playing clock every frame, not every render.
  const playMsRef = useRef(0)
  const matchRef = useRef({ m, receivedAt: live.receivedAt, delayS: config.delayS })
  matchRef.current = { m, receivedAt: live.receivedAt, delayS: config.delayS }
  useEffect(() => {
    let raf = 0
    const loop = () => {
      const { m: cur, receivedAt, delayS } = matchRef.current
      if (cur) playMsRef.current = playClock(liveClock(cur, receivedAt, Date.now()), cur.speed, delayS)
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [])

  const [meta, setMeta] = useState<Meta | null>(null)
  const haveMeta = !!(m?.home && m.away)
  useEffect(() => {
    setMeta(null)
    if (!id || !haveMeta) return
    const ctl = new AbortController()
    void getMeta(id, BRAIN_URL, ctl.signal).then(setMeta).catch(() => undefined)
    return () => ctl.abort()
  }, [id, haveMeta])
  const { tracking, ready } = useLiveTracking(meta ? id : null, playMsRef)
  const replay = useMemo(() => (id && meta ? liveReplay(id, meta, tracking, live.moments) : null), [id, meta, tracking, live.moments.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const next = () => {
    onMatch(null)
    void tune({ next: true }).then(setTuned).catch(() => undefined)
    setRetune((n) => n + 1)
  }

  if (!brainConfigured) {
    return (
      <main className="live-page">
        <Nav lang={lang} mode={mode} onProfile={onProfile} />
        <p className="caveat">{t(lang, 'live.nobrain')}</p>
      </main>
    )
  }

  const shownEvents = live.events.filter((e) => e.clock.matchMs <= playMs)
  const [hs, as] = scoreOf(shownEvents, m?.home?.id, m?.away?.id)
  const stories = live.overlays.filter((o) => o.kind === 'lower_third' && o.cohort.language === lang && o.cohort.mode === mode && o.cohort.perspective === 'neutral')
  const writers = { model: 0, mended: 0, template: 0 }
  for (const o of stories) writers[writer(o)]++
  const delay = median(m ? pipelineDelays(m, live.moments, live.overlays) : [])
  const stages = m ? stageDelays(m, live.moments, live.overlays) : { interpret: [], write: [] }
  const detectS = median(stages.interpret)
  const writeS = median(stages.write)
  const due = useMemo(
    () => dueOverlays(live.overlays, lang, mode, playMs),
    // The clock moves every tick, the list only when a new overlay becomes due: key on what it would show.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [live.overlays, lang, mode, Math.floor(playMs / 5000)],
  )
  const waiting = !id && season && season.seasonId && season.done < season.total

  return (
    <main className="live-page">
      <Nav lang={lang} mode={mode} onProfile={onProfile} onNext={id ? next : undefined} />

      {!id && (
        <section className="live-card live-tuning" aria-live="polite">
          <p role="status" className="hint">
            {waiting ? t(lang, 'season.channel.simulating').replace('{done}', String(season.done)).replace('{total}', String(season.total)) : t(lang, 'season.channel.tuning')}
          </p>
          <LoadBar seconds={waiting ? 60 : 25} />
        </section>
      )}

      {id && (
        <>
          <section className="live-card live-board" aria-live="polite">
            {m?.home && m.away ? (
              <>
                <div className="live-score"><span>{m.home.name}</span><b>{hs} – {as}</b><span>{m.away.name}</span></div>
                <div className="live-meta">
                  {tuned && !named && <span className="muted">{t(lang, 'season.channel.round').replace('{n}', String(tuned.round))}</span>}
                  <span className={`live-status ${m.status}`}>{t(lang, `live.status.${m.status ?? 'scheduled'}`)}</span>
                  <span className="live-clock">{clockLabel(playMs)}</span>
                  <span className="muted">{t(lang, 'live.feedAt')} {clockLabel(liveMs)} · {m.speed}× {t(lang, 'live.speed')}</span>
                  <span className={`live-push ${push}`} title={t(lang, 'live.push.title')}>{t(lang, `live.push.${push}`)}</span>
                </div>
              </>
            ) : (
              <><p role="status" className="hint">{t(lang, 'live.starting')}</p><LoadBar seconds={15} /></>
            )}
            {live.error && <p className="caveat">{t(lang, 'live.error')}</p>}
            {fullTime && !named && <p role="status" className="hint">{t(lang, 'season.channel.fulltime').replace('{n}', String(Math.max(countdown, 0)))}</p>}
          </section>

          <section className="live-card live-watch-card" aria-label={t(lang, 'live.watch')}>
            <div className="live-watch-head">
              <h2>{t(lang, 'live.watch')}</h2>
              <span className="muted">{t(lang, 'live.behind').replace('{n}', String(config.delayS))}</span>
              <span className="live-cams">
                {(['2d', 'bc', 'end', 'top'] as const).map((c) => <button key={c} type="button" className={`chip${c === cam ? ' on' : ''}`} aria-pressed={c === cam} onClick={() => setCam(c)}>{t(lang, `live.cam.${c}`)}</button>)}
              </span>
            </div>
            <div className="live-watch">
              {replay && ready ? (
                <Screen replay={replay} ms={playMs} msRef={playMsRef} profile={profile} evidenceMoment={null} onWhy={() => undefined} overlays={live.overlays} cam={cam} />
              ) : (
                <div className="live-watch-wait"><p role="status" className="hint">{t(lang, 'live.pitchWait')}</p><LoadBar seconds={20} /></div>
              )}
            </div>
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
              {season?.seasonId && (
                <>
                  <h2>{t(lang, 'season.channel.table')} · <a href="#/season">{t(lang, 'season.link')}</a></h2>
                  <p className="muted season-note">{t(lang, 'season.channel.asBroadcast')}</p>
                  <SeasonTable rows={season.standingsAired} clubs={season.clubs} lang={lang} compact highlight={m?.home && m.away ? [m.home.id, m.away.id] : []} />
                </>
              )}
              <h2>{t(lang, 'live.events')}</h2>
              {shownEvents.length === 0 && <p className="muted">{t(lang, 'live.empty')}</p>}
              <ul className="live-events">
                {[...shownEvents].slice(-10).reverse().map((e) => <li key={e.n}>{eventLine(e, m)}</li>)}
              </ul>
            </section>
          </div>

          <section className="live-card" aria-label={t(lang, 'live.stages')}>
            <h2>{t(lang, 'live.stages')}</h2>
            <ol className="live-stages">
              <Stage name={t(lang, 'live.stage.feed')} value={String(live.events.length ? live.events[live.events.length - 1].n : 0)} note={t(lang, 'live.stage.feed.d')} />
              <Stage name={t(lang, 'live.stage.interpret')} value={String(live.moments.length)} note={t(lang, 'live.stage.interpret.d')} />
              <Stage name={t(lang, 'live.stage.agents')} value={String(writers.model + writers.mended + writers.template)} note={`${writers.model} / ${writers.mended} / ${writers.template} ${t(lang, 'live.writers')}`} />
              <Stage
                name={t(lang, 'live.stage.delay')}
                value={delay === null ? '–' : `${delay.toFixed(1)} ${t(lang, 'live.seconds')}`}
                note={detectS === null || writeS === null ? t(lang, 'live.stage.delay.d') : t(lang, 'live.stage.delay.split').replace('{a}', detectS.toFixed(1)).replace('{b}', writeS.toFixed(1))}
              />
            </ol>
            <h2>{t(lang, 'live.moments')}</h2>
            {live.moments.length === 0 && <p className="muted">{t(lang, 'live.empty')}</p>}
            <ul className="live-moments">
              {[...live.moments].reverse().slice(0, 8).map((mo) => (
                <li key={mo.id}><span className="muted">{Math.floor(mo.detectedAt.matchMs / 60000)}′</span> {momentTypeLabel(lang, mo.type)} <span className="muted">{mo.salience.toFixed(2)}</span></li>
              ))}
            </ul>
          </section>
        </>
      )}

      <details className="live-about">
        <summary>{t(lang, 'live.about')}</summary>
        <p>{t(lang, 'live.about.body')}</p>
      </details>
    </main>
  )
}

function Nav({ lang, mode, onProfile, onNext }: { lang: Profile['language']; mode: Profile['mode']; onProfile: (p: Partial<Profile>) => void; onNext?: () => void }) {
  return (
    <header className="live-head">
      <nav className="live-nav">
        <strong className="live-brand">MatchMind</strong>
        <a className="btn" href="#/season">{t(lang, 'season.link')}</a>
        <a className="btn" href="#/replay">{t(lang, 'season.replays')}</a>
        {onNext && <button type="button" className="btn" onClick={onNext}>{t(lang, 'season.channel.next')}</button>}
        <span className="live-lang">
          {(['en', 'es', 'tr'] as const).map((l) => <button key={l} type="button" className={`chip${l === lang ? ' on' : ''}`} aria-pressed={l === lang} onClick={() => onProfile({ language: l })}>{l.toUpperCase()}</button>)}
          {(['casual', 'analyst'] as const).map((x) => <button key={x} type="button" className={`chip${x === mode ? ' on' : ''}`} aria-pressed={x === mode} onClick={() => onProfile({ mode: x })}>{t(lang, x)}</button>)}
        </span>
      </nav>
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
export function dueOverlays(overlays: LiveOverlay[], lang: Profile['language'], mode: Profile['mode'], clockMs: number): LiveOverlay[] {
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

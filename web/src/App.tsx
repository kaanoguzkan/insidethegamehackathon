import { useCallback, useEffect, useMemo, useState } from 'react'
import { EvidenceDrawer } from './components/EvidenceDrawer'
import { Home } from './components/Home'
import { Brand, SiteNav } from './components/SiteNav'
import { isViewId, type ViewId } from './components/insights/Insights'
import { MatchStrip } from './components/MatchStrip'
import { Popover } from './components/Popover'
import { ProfilePanel } from './components/ProfilePanel'
import { PANEL_TABS, Rail, type PanelTab } from './components/Rail'
import { Screen } from './components/Screen'
import { StageHead } from './components/StageHead'
import { useClock } from './hooks/useClock'
import { buildHash, useRoute } from './hooks/useHash'
import { useLiveBrain } from './hooks/useLiveBrain'
import { useLiveFollow } from './hooks/useLiveFollow'
import { useStream, type StreamHandle } from './hooks/useStream'
import { t } from './i18n'
import { brainConfigured, cohortKey } from './lib/brain'
import { cohortForMatch } from './lib/cohort'
import { VisionPanel } from './components/VisionPanel'
import { addStreamCohort, LIVE_DELAY_S, nearestStreamSpeed, nextStreamSpeed, setStreamSpeed, startStream, STREAM_SPEEDS, stopStream } from './lib/stream'
import { totalMs } from './lib/clock'
import { LAYER_KEYS, NO_LAYERS, type Layers } from './lib/layers'
import type { Cam } from './lib/webgl'
import { type Health, loadIndex, loadReplay, loadVariant, overlaysFor, type Replay } from './lib/data'
import { DEFAULT_PROFILE, type Overlay, type Profile, type ReplayIndexEntry } from './lib/types'

function useReplay(id: string | null) {
  const [replay, setReplay] = useState<Replay | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (!id) return
    let live = true
    setReplay(null)
    setError(null)
    loadReplay(id)
      .then((r) => live && setReplay(r))
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [id])
  return { replay, error }
}

export function App() {
  const [route, setRoute] = useRoute()
  const [index, setIndex] = useState<ReplayIndexEntry[] | null>(null)
  const [indexError, setIndexError] = useState<string | null>(null)
  useEffect(() => {
    loadIndex().then(setIndex).catch((e: Error) => setIndexError(e.message))
  }, [])
  // Only ids the index lists are loaded; anything else in the URL falls back to the first match.
  const known = new Set((index ?? []).map((m) => m.id))
  const matchId = route.match && known.has(route.match) ? route.match : (index?.[0]?.id ?? null)
  const { replay, error } = useReplay(route.stream ? null : matchId)
  const lang = route.profile.language

  if (route.stream) return <LiveMatch streamId={route.stream} route={route} setRoute={setRoute} />

  if (indexError || error) {
    return (
      <div className="state">
        <h1>{t(lang, 'failed')}</h1>
        <p>{indexError ?? error}</p>
        <p className="muted">pnpm sync && pnpm dev</p>
      </div>
    )
  }
  if (!replay || !matchId) {
    return (
      <div className="state" role="status">
        <div className="spinner" aria-hidden="true" />
        <p>{t(lang, 'loading')}</p>
      </div>
    )
  }
  return <Player key={replay.id} replay={replay} index={index ?? []} route={route} setRoute={setRoute} />
}

/** A match being played live: wait for the first answer, then hand the match center the replay that grows. */
function LiveMatch({ streamId, route, setRoute }: { streamId: string; route: ReturnType<typeof useRoute>[0]; setRoute: ReturnType<typeof useRoute>[1] }) {
  const stream = useStream(streamId)
  const lang = route.profile.language
  if (stream.status === 'gone') {
    return (
      <div className="state">
        <h1>{t(lang, 'stream.gone')}</h1>
        <p>{t(lang, 'stream.goneHint')}</p>
        <button type="button" className="btn" onClick={() => setRoute({ stream: null })}>{t(lang, 'stream.exit')}</button>
      </div>
    )
  }
  if (!stream.replay) {
    return (
      <div className="state" role="status">
        <div className="spinner" aria-hidden="true" />
        <p>{stream.error ?? t(lang, 'stream.connecting')}</p>
      </div>
    )
  }
  return <Player key={streamId} replay={stream.replay} index={[]} route={route} setRoute={setRoute} stream={stream} />
}

function Player({ replay, index, route, setRoute, stream }: { replay: Replay; index: ReplayIndexEntry[]; route: ReturnType<typeof useRoute>[0]; setRoute: ReturnType<typeof useRoute>[1]; stream?: StreamHandle }) {
  const total = stream ? Math.max(stream.durationMs, 1) : totalMs(replay.meta)
  const broadcast = route.view === 'broadcast'
  const clock = useClock(total, broadcast ? 1 : 5)
  const { ms, msRef, playing, setPlaying, speed } = clock
  const follow = useLiveFollow(stream, clock)
  // Each visit: say what this is and put watching it live first. Remembered for the session once dismissed, and never in the way of a link that starts at a given minute.
  const [welcome, setWelcome] = useState(() => {
    if (stream || route.view === 'broadcast' || route.t !== null) return false
    try {
      return window.sessionStorage.getItem('mm.welcome') !== '1'
    } catch {
      return true
    }
  })
  const closeWelcome = useCallback(() => {
    setWelcome(false)
    try {
      window.sessionStorage.setItem('mm.welcome', '1')
    } catch {
      /* private window: it will be shown again next time */
    }
  }, [])
  useEffect(() => {
    if (welcome && (playing || ms > 0)) closeWelcome()
  }, [welcome, playing, ms, closeWelcome])
  // In a live match any move of the playhead is a rewind: it detaches the viewer from the live picture until they go back to live.
  const seek = useCallback((to: number) => { follow.detach(); clock.seek(to) }, [follow.detach, clock.seek]) // eslint-disable-line react-hooks/exhaustive-deps
  const toggle = useCallback(() => { if (stream) follow.detach(); clock.toggle() }, [stream, follow.detach, clock.toggle]) // eslint-disable-line react-hooks/exhaustive-deps
  // In a live match the speed is the match's own: the server plays it faster or slower from this minute, and the viewer stays on the live picture.
  const setSpeed = useCallback((v: number) => { if (stream) void setStreamSpeed(stream.id, nearestStreamSpeed(v)).catch(() => undefined); else clock.setSpeed(v) }, [stream, clock.setSpeed]) // eslint-disable-line react-hooks/exhaustive-deps
  const profile = route.profile
  const lang = profile.language
  const [selected, setSelected] = useState<string | null>(null)
  const [showOnPitch, setShowOnPitch] = useState(true)
  const [layers, setLayers] = useState<Layers>(NO_LAYERS)
  const [railTab, setRailTab] = useState<Exclude<PanelTab, 'moments' | 'numbers'>>('story')
  const step = route.step
  const cam: Cam = route.cam ?? (typeof window !== 'undefined' && window.matchMedia('(max-width: 760px)').matches ? '2d' : 'tv')
  const exploreTab: ViewId = isViewId(route.tab) ? route.tab : 'win'
  // One tab bar: Moments is the Watch step, Numbers the Explore step, the rest the Understand step (the step stays in the link, so a shared link opens the same panel).
  const panelTab: PanelTab = step === 'watch' ? 'moments' : step === 'explore' ? 'numbers' : railTab
  const selectTab = (tab: PanelTab | undefined) => {
    if (!tab) return
    if (tab === 'moments') setRoute({ step: 'watch' })
    else if (tab === 'numbers') setRoute({ step: 'explore' })
    else {
      setRailTab(tab)
      setRoute({ step: 'understand' })
    }
  }
  // The site menu: each of these is one click from anywhere.
  const goLive = () => { closeWelcome(); void startStream(replay.id, 5, liveCohorts, 0).then((st) => setRoute({ stream: st.streamId })).catch(() => undefined) }
  const goReplay = () => { closeWelcome(); if (stream) { void stopStream(stream.id); setRoute({ stream: null }) } else selectTab('moments') }
  const goAsk = () => { closeWelcome(); selectTab('ask') }
  // A link from another page (#/?go=live, #/?go=ask) does its thing once, then the address goes back to what it was.
  useEffect(() => {
    const m = /[?&]go=(live|ask)/.exec(window.location.hash)
    if (!m) return
    window.history.replaceState(null, '', window.location.hash.replace(/[?&]go=(live|ask)/, '') || '#/')
    if (m[1] === 'live' && brainConfigured && !stream) goLive()
    if (m[1] === 'ask') goAsk()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const goHome = () => { if (stream) { void stopStream(stream.id); setRoute({ stream: null }) } setWelcome(true) }
  const [health, setHealth] = useState<Health>('healthy')
  const [variants, setVariants] = useState<Partial<Record<Health, Overlay[]>>>({})
  useEffect(() => {
    if (health === 'healthy' || variants[health]) return
    loadVariant(replay.id, health).then((o) => setVariants((v) => ({ ...v, [health]: o }))).catch(() => setHealth('healthy'))
  }, [health, replay.id, variants])
  const live = useLiveBrain(stream ? '' : replay.id) // Live AI rewrites a recorded match's story on demand: a live match's story is written as it is played
  const overlays = useMemo(() => live.merge(overlaysFor(replay, health, variants)), [replay, health, variants, live.merge])
  const hasVariants = Object.keys(replay.meta.package.variants ?? {}).length > 0
  const [profileB, setProfileB] = useState<Profile>({ ...DEFAULT_PROFILE, mode: profile.mode === 'analyst' ? 'casual' : 'analyst', language: profile.language === 'es' ? 'en' : 'es' })

  // With Live AI on, selecting a moment asks the Brain for a fresh story for each viewer on screen.
  const liveCohorts = useMemo(() => (route.split ? [profile, profileB] : [profile]).map((p) => cohortForMatch(p, replay.meta)), [route.split, profile, profileB, replay.meta])
  useEffect(() => {
    if (selected) live.explain(selected, liveCohorts)
  }, [selected, liveCohorts, live.explain])

  // Jump to the start time from the URL once, and autoplay the overlay-only page.
  useEffect(() => {
    if (route.t !== null && !stream) clock.seek(route.t)
    if (broadcast) setPlaying(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // The model writes a live match's story for the viewers on screen: tell the session when the profile changes (moments still to come only).
  const cohortsId = liveCohorts.map(cohortKey).join('|')
  useEffect(() => {
    if (!stream) return
    for (const c of liveCohorts) void addStreamCohort(stream.id, c).catch(() => undefined)
  }, [stream?.id, cohortsId]) // eslint-disable-line react-hooks/exhaustive-deps

  const setProfile = useCallback((p: Profile) => setRoute({ profile: p }), [setRoute])

  const pick = useCallback(
    (id: string) => {
      const m = replay.moments.find((x) => x.id === id)
      if (!m) return
      setSelected(id)
      seek(Math.max(0, m.detectedAt.matchMs - 6000))
    },
    [replay, seek],
  )
  const moment = useMemo(() => replay.moments.find((m) => m.id === selected) ?? null, [replay, selected])

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(tag) && !(e.target as HTMLInputElement).type?.match(/range/)) return
      if (e.key === ' ' && tag !== 'BUTTON') {
        e.preventDefault()
        toggle()
      } else if (e.key === 'ArrowRight') seek(msRef.current + (e.shiftKey ? 60_000 : 10_000))
      else if (e.key === 'ArrowLeft') seek(msRef.current - (e.shiftKey ? 60_000 : 10_000))
      else if (e.key === ']') setSpeed(stream ? nextStreamSpeed(speed, 1) : Math.min(60, speed * 2))
      else if (e.key === '[') setSpeed(stream ? nextStreamSpeed(speed, -1) : Math.max(1, Math.round(speed / 2)))
      else if (e.key === 'Escape') setSelected(null)
      else if (e.key >= '1' && e.key <= '5' && !e.metaKey && !e.ctrlKey && !e.altKey) selectTab(PANEL_TABS[Number(e.key) - 1])
    }
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [toggle, seek, msRef, speed, setSpeed, setRoute])

  if (broadcast) {
    return (
      <div className="broadcast">
        <Screen replay={replay} ms={ms} msRef={msRef} profile={profile} evidenceMoment={null} onWhy={() => undefined} overlayOnly />
      </div>
    )
  }

  const broadcastHref = buildHash({ view: 'broadcast', match: replay.id, profile: { ...profile, density: profile.density === 'high' ? 'high' : 'low' }, split: false, t: Math.round(ms / 60000), step: 'watch', tab: null, cam: null, follow: false, stream: null })
  const onLayer = (k: (typeof LAYER_KEYS)[number]) => setLayers((l) => ({ ...l, [k]: !l[k] }))
  const onLens = (keys: (keyof Layers)[], on: boolean) => setLayers((l) => ({ ...l, ...Object.fromEntries(keys.map((k) => [k, on])) }))
  const screens = route.split
    ? [
        { profile, title: `${t(lang, profile.mode)} · ${profile.language.toUpperCase()}` },
        { profile: profileB, title: `${t(profileB.language, profileB.mode)} · ${profileB.language.toUpperCase()}` },
      ]
    : [{ profile, title: undefined }]
  const viewerSummary = `${t(lang, profile.mode)} · ${profile.language.toUpperCase()}${route.split ? ' + ' + `${t(profileB.language, profileB.mode)} · ${profileB.language.toUpperCase()}` : ''}`

  return (
    <div className={`app${profile.highContrast ? ' hc' : ''}`}>
      <header className="topbar">
        <div className="tb-left">
          <Brand lang={lang} onClick={goHome} />
          {stream ? (
            <span className="live-badge" role="status">
              <span className="live-dot" aria-hidden="true" />
              <b>{t(lang, stream.status === 'finished' ? 'stream.fulltime' : 'stream.live')}</b>
              <small>{stream.speed}× · {LIVE_DELAY_S} s {t(lang, 'stream.delay')}</small>
            </span>
          ) : (
            <label className="match-pick">
              <span className="sr-only">{t(lang, 'selectMatch')}</span>
              <select value={replay.id} onChange={(e) => setRoute({ match: e.target.value })} aria-label={t(lang, 'selectMatch')}>
                {index.map((m) => (
                  <option key={m.id} value={m.id}>{m.title} · {m.score[m.home]}–{m.score[m.away]}</option>
                ))}
              </select>
            </label>
          )}
        </div>

        <SiteNav lang={lang} active={stream ? 'live' : 'replay'} liveAvailable={brainConfigured} onLive={stream ? () => follow.goLive() : goLive} onReplay={goReplay} onAsk={goAsk} />

        <div className="tb-right">
          {stream && !follow.following && <button type="button" className="btn live" onClick={follow.goLive}>{t(lang, 'stream.back')}</button>}
          <Popover label={<><span className="pop-key">{t(lang, 'viewer')}</span><span className="pop-val">{viewerSummary}</span></>} title={t(lang, 'viewer')} className="viewer-pop">
            <ProfilePanel profile={profile} onChange={setProfile} replay={replay} heading={route.split ? `${t(lang, 'viewer')} A` : undefined} />
            {route.split && <ProfilePanel profile={profileB} onChange={setProfileB} replay={replay} heading={`${t(lang, 'viewer')} B`} />}
            <button type="button" className={`btn wide${route.split ? ' on' : ''}`} aria-pressed={route.split} onClick={() => setRoute({ split: !route.split })}>
              {route.split ? t(lang, 'singleView') : t(lang, 'splitView')}
            </button>
          </Popover>
          {!stream && (
            <Popover
              label={<><span className={`health-dot h-${health}`} aria-hidden="true" /><span className="pop-key">{t(lang, 'tools.menu')}</span></>}
              title={t(lang, 'tools.title')}
              className="tools-pop"
            >
              <p className="pop-title">{t(lang, 'tools.title')}</p>
              {hasVariants && (
                <>
                  <p className="hint">{t(lang, 'healthNote')}</p>
                  <div className="seg stacked" role="radiogroup" aria-label={t(lang, 'health')}>
                    {(['healthy', 'unreliable', 'outage'] as const).map((h) => (
                      <button key={h} type="button" role="radio" aria-checked={health === h} className={`${health === h ? 'on' : ''} h-${h}`} onClick={() => setHealth(h)}>
                        <span className={`health-dot h-${h}`} aria-hidden="true" />
                        {t(lang, h === 'healthy' ? 'healthHealthy' : h === 'unreliable' ? 'healthUnreliable' : 'healthOutage')}
                      </button>
                    ))}
                  </div>
                </>
              )}
              <div className="tools-list">
                {live.available && (
                  <button type="button" className={`btn live${live.enabled ? ' on' : ''}`} aria-pressed={live.enabled} onClick={live.toggle} title={t(lang, 'liveAIHint')}>
                    {live.enabled && <span className={`health-dot h-${live.status === 'ready' ? 'healthy' : live.status === 'waking' ? 'unreliable' : 'outage'}`} aria-hidden="true" />}
                    {t(lang, 'tools.ai')}
                    <span className="tools-state">{t(lang, live.enabled ? 'tools.aiOn' : 'tools.aiOff')}</span>
                  </button>
                )}
                <a className="btn" href={`${import.meta.env.BASE_URL}replays/${replay.id}/report.pdf`} target="_blank" rel="noreferrer" title={t(lang, 'reportHint')}>{t(lang, 'report')}</a>
                <a className="btn" href={broadcastHref} target="_blank" rel="noreferrer">{t(lang, 'broadcastLink')}</a>
              </div>
            </Popover>
          )}
          {stream && <button type="button" className="btn" onClick={() => { void stopStream(stream.id); setRoute({ stream: null }) }}>{t(lang, 'stream.exit')}</button>}
        </div>
      </header>

      <main className="workspace" data-step={step}>
        <section className="stage-col">
          <StageHead replay={replay} ms={ms} lang={lang} />
          <div className="stage-slot">
            {welcome && (
              <Home
                lang={lang}
                profile={profile}
                onProfile={(p) => setProfile({ ...profile, ...p })}
                onLive={brainConfigured ? goLive : undefined}
                onAsk={brainConfigured ? goAsk : undefined}
                onReplay={() => { closeWelcome(); clock.toggle() }}
                onSkip={closeWelcome}
              />
            )}
            {stream && <VisionPanel lang={lang} streamId={stream.id} msRef={msRef} />}
            {screens.map((sc, i) => (
              <div className="cell" key={i}>
                <Screen replay={replay} ms={ms} msRef={msRef} profile={sc.profile} evidenceMoment={showOnPitch ? selected : null} onWhy={pick} overlays={overlays} layers={layers} title={sc.title} cam={cam} follow={route.follow} />
              </div>
            ))}
          </div>
        </section>
        <Rail tab={panelTab} onTab={selectTab} replay={replay} profile={profile} ms={ms} selected={selected} onPick={pick} live={!!stream} streamId={stream?.id} numbersTab={exploreTab} onNumbersTab={(tab) => setRoute({ tab })} layers={layers} onLens={onLens} />
      </main>

      <MatchStrip replay={replay} ms={ms} playing={playing} speed={stream ? nearestStreamSpeed(stream.speed) : speed} lang={lang} layers={layers} selected={selected} cam={cam} follow={route.follow} onCam={(c) => setRoute({ cam: c })} onFollow={(on) => setRoute({ follow: on })} toggle={toggle} setSpeed={setSpeed} speeds={stream ? STREAM_SPEEDS : undefined} seek={seek} onPick={pick} onLayer={onLayer} onClearLayers={() => setLayers(NO_LAYERS)} />
      <EvidenceDrawer moment={moment} replay={replay} lang={lang} onClose={() => setSelected(null)} onSeek={seek} showOnPitch={showOnPitch} setShowOnPitch={setShowOnPitch} health={health} live={stream ? undefined : live} />
      <footer className="foot">
        <span>{t(lang, 'synthetic')}</span>
        <span>{t(lang, 'poweredBy')}</span>
      </footer>
    </div>
  )
}

import { useCallback, useEffect, useMemo, useState } from 'react'
import { EvidenceDrawer } from './components/EvidenceDrawer'
import { Insights, isViewId, type ViewId } from './components/insights/Insights'
import { MatchStrip } from './components/MatchStrip'
import { Popover } from './components/Popover'
import { ProfilePanel } from './components/ProfilePanel'
import { Rail, type RailTab } from './components/Rail'
import { Screen } from './components/Screen'
import { StageHead } from './components/StageHead'
import { useClock } from './hooks/useClock'
import { buildHash, STEPS, type Step, useRoute } from './hooks/useHash'
import { t } from './i18n'
import { totalMs } from './lib/clock'
import { LAYER_KEYS, NO_LAYERS, type Layers } from './lib/layers'
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
  const { replay, error } = useReplay(matchId)
  const lang = route.profile.language

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

function Player({ replay, index, route, setRoute }: { replay: Replay; index: ReplayIndexEntry[]; route: ReturnType<typeof useRoute>[0]; setRoute: ReturnType<typeof useRoute>[1] }) {
  const total = totalMs(replay.meta)
  const broadcast = route.view === 'broadcast'
  const clock = useClock(total, broadcast ? 1 : 10)
  const { ms, msRef, seek, toggle, playing, setPlaying, speed, setSpeed } = clock
  const profile = route.profile
  const lang = profile.language
  const [selected, setSelected] = useState<string | null>(null)
  const [showOnPitch, setShowOnPitch] = useState(true)
  const [layers, setLayers] = useState<Layers>(NO_LAYERS)
  const [railTab, setRailTab] = useState<RailTab>('story')
  const step = route.step
  const exploreTab: ViewId = isViewId(route.tab) ? route.tab : 'win'
  const [health, setHealth] = useState<Health>('healthy')
  const [variants, setVariants] = useState<Partial<Record<Health, Overlay[]>>>({})
  useEffect(() => {
    if (health === 'healthy' || variants[health]) return
    loadVariant(replay.id, health).then((o) => setVariants((v) => ({ ...v, [health]: o }))).catch(() => setHealth('healthy'))
  }, [health, replay.id, variants])
  const overlays = useMemo(() => overlaysFor(replay, health, variants), [replay, health, variants])
  const hasVariants = Object.keys(replay.meta.package.variants ?? {}).length > 0
  const [profileB, setProfileB] = useState<Profile>({ ...DEFAULT_PROFILE, mode: profile.mode === 'analyst' ? 'casual' : 'analyst', language: profile.language === 'es' ? 'en' : 'es' })

  // Jump to the start time from the URL once, and autoplay the overlay-only page.
  useEffect(() => {
    if (route.t !== null) seek(route.t)
    if (broadcast) setPlaying(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
      else if (e.key === ']') setSpeed(Math.min(60, speed * 2))
      else if (e.key === '[') setSpeed(Math.max(1, Math.round(speed / 2)))
      else if (e.key === 'Escape') setSelected(null)
      else if (e.key >= '1' && e.key <= '3' && !e.metaKey && !e.ctrlKey && !e.altKey) setRoute({ step: STEPS[Number(e.key) - 1] })
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

  const broadcastHref = buildHash({ view: 'broadcast', match: replay.id, profile, split: false, t: Math.round(ms / 60000), step: 'watch', tab: null })
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
          <div className="brand">
            <svg width="24" height="24" viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="10" fill="none" stroke="currentColor" strokeWidth="3" /><circle cx="16" cy="16" r="3" fill="currentColor" /></svg>
            <b>{t(lang, 'appTitle')}</b>
          </div>
          <label className="match-pick">
            <span className="sr-only">{t(lang, 'selectMatch')}</span>
            <select value={replay.id} onChange={(e) => setRoute({ match: e.target.value })} aria-label={t(lang, 'selectMatch')}>
              {index.map((m) => (
                <option key={m.id} value={m.id}>{m.title} · {m.score[m.home]}–{m.score[m.away]}</option>
              ))}
            </select>
          </label>
        </div>

        <nav className="steps" aria-label={t(lang, 'path')}>
          {STEPS.map((id, i) => (
            <button key={id} type="button" className={step === id ? 'on' : ''} aria-current={step === id ? 'step' : undefined} onClick={() => setRoute({ step: id })} title={`${t(lang, `step.${id}.d`)} (${i + 1})`}>
              <span className="step-n" aria-hidden="true">{i + 1}</span>
              {t(lang, `step.${id}`)}
            </button>
          ))}
        </nav>

        <div className="tb-right">
          <Popover label={<><span className="pop-key">{t(lang, 'viewer')}</span><span className="pop-val">{viewerSummary}</span></>} title={t(lang, 'viewer')} className="viewer-pop">
            <ProfilePanel profile={profile} onChange={setProfile} replay={replay} heading={route.split ? `${t(lang, 'viewer')} A` : undefined} />
            {route.split && <ProfilePanel profile={profileB} onChange={setProfileB} replay={replay} heading={`${t(lang, 'viewer')} B`} />}
            <button type="button" className={`btn wide${route.split ? ' on' : ''}`} aria-pressed={route.split} onClick={() => setRoute({ split: !route.split })}>
              {route.split ? t(lang, 'singleView') : t(lang, 'splitView')}
            </button>
          </Popover>
          {hasVariants && (
            <Popover label={<><span className={`health-dot h-${health}`} aria-hidden="true" /><span className="pop-key">{t(lang, 'health')}</span><span className="pop-val">{t(lang, health === 'healthy' ? 'healthHealthy' : health === 'unreliable' ? 'healthUnreliable' : 'healthOutage')}</span></>} title={t(lang, 'health')}>
              <p className="pop-title">{t(lang, 'health')}</p>
              <p className="hint">{t(lang, 'healthNote')}</p>
              <div className="seg stacked" role="radiogroup" aria-label={t(lang, 'health')}>
                {(['healthy', 'unreliable', 'outage'] as const).map((h) => (
                  <button key={h} type="button" role="radio" aria-checked={health === h} className={`${health === h ? 'on' : ''} h-${h}`} onClick={() => setHealth(h)}>
                    <span className={`health-dot h-${h}`} aria-hidden="true" />
                    {t(lang, h === 'healthy' ? 'healthHealthy' : h === 'unreliable' ? 'healthUnreliable' : 'healthOutage')}
                  </button>
                ))}
              </div>
            </Popover>
          )}
          <a className="btn" href={`${import.meta.env.BASE_URL}replays/${replay.id}/report.pdf`} target="_blank" rel="noreferrer" title={t(lang, 'reportHint')}>{t(lang, 'report')}</a>
          <a className="btn" href={broadcastHref} target="_blank" rel="noreferrer">{t(lang, 'broadcastLink')}</a>
        </div>
      </header>

      <main className="workspace" data-step={step}>
        <section className="stage-col">
          <StageHead replay={replay} ms={ms} lang={lang} />
          <div className="stage-slot">
            {screens.map((sc, i) => (
              <div className="cell" key={i}>
                <Screen replay={replay} ms={ms} msRef={msRef} profile={sc.profile} evidenceMoment={showOnPitch ? selected : null} onWhy={pick} overlays={overlays} layers={layers} title={sc.title} />
              </div>
            ))}
          </div>
        </section>
        {step === 'explore' ? (
          <Insights replay={replay} ms={ms} lang={lang} tab={exploreTab} onTab={(tab) => setRoute({ tab })} layers={layers} onLens={onLens} />
        ) : (
          <Rail step={step} tab={railTab} onTab={setRailTab} onStep={(s: Step) => setRoute({ step: s })} replay={replay} profile={profile} ms={ms} selected={selected} onPick={pick} />
        )}
      </main>

      <MatchStrip replay={replay} ms={ms} playing={playing} speed={speed} lang={lang} layers={layers} selected={selected} toggle={toggle} setSpeed={setSpeed} seek={seek} onPick={pick} onLayer={onLayer} onClearLayers={() => setLayers(NO_LAYERS)} />
      <EvidenceDrawer moment={moment} replay={replay} lang={lang} onClose={() => setSelected(null)} onSeek={seek} showOnPitch={showOnPitch} setShowOnPitch={setShowOnPitch} health={health} />
      <footer className="foot">
        <span>{t(lang, 'synthetic')}</span>
        <span>{t(lang, 'poweredBy')}</span>
      </footer>
    </div>
  )
}

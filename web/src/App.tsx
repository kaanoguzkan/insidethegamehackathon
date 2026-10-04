import { useCallback, useEffect, useMemo, useState } from 'react'
import { EvidenceDrawer } from './components/EvidenceDrawer'
import { MomentList } from './components/MomentList'
import { ProfilePanel } from './components/ProfilePanel'
import { RecapPanel } from './components/RecapPanel'
import { Screen } from './components/Screen'
import { Timeline } from './components/Timeline'
import { Transport } from './components/Transport'
import { useClock } from './hooks/useClock'
import { buildHash, useRoute } from './hooks/useHash'
import { t } from './i18n'
import { totalMs } from './lib/clock'
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
    }
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [toggle, seek, msRef, speed, setSpeed])

  if (broadcast) {
    return (
      <div className="broadcast">
        <Screen replay={replay} ms={ms} msRef={msRef} profile={profile} evidenceMoment={null} onWhy={() => undefined} overlayOnly />
      </div>
    )
  }

  const broadcastHref = buildHash({ view: 'broadcast', match: replay.id, profile, split: false, t: Math.round(ms / 60000) })
  return (
    <div className={`app${profile.highContrast ? ' hc' : ''}`}>
      <header className="topbar">
        <div className="brand">
          <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="10" fill="none" stroke="var(--accent)" strokeWidth="3" /><circle cx="16" cy="16" r="3" fill="var(--accent)" /></svg>
          <div><b>{t(lang, 'appTitle')}</b><small>{t(lang, 'tagline')}</small></div>
        </div>
        <label className="field inline">
          <span>{t(lang, 'match')}</span>
          <select value={replay.id} onChange={(e) => setRoute({ match: e.target.value })} aria-label={t(lang, 'selectMatch')}>
            {index.map((m) => (
              <option key={m.id} value={m.id}>{m.title} · {m.score[m.home]}–{m.score[m.away]}</option>
            ))}
          </select>
        </label>
        {hasVariants && (
          <div className="health" role="radiogroup" aria-label={t(lang, 'health')} title={t(lang, 'healthNote')}>
            <span>{t(lang, 'health')}</span>
            {(['healthy', 'unreliable', 'outage'] as const).map((h) => (
              <button key={h} type="button" role="radio" aria-checked={health === h} className={`${health === h ? 'on' : ''} h-${h}`} onClick={() => setHealth(h)}>
                {t(lang, h === 'healthy' ? 'healthHealthy' : h === 'unreliable' ? 'healthUnreliable' : 'healthOutage')}
              </button>
            ))}
          </div>
        )}
        <div className="actions">
          <button type="button" className={`btn${route.split ? ' on' : ''}`} aria-pressed={route.split} onClick={() => setRoute({ split: !route.split })}>
            {route.split ? t(lang, 'singleView') : t(lang, 'splitView')}
          </button>
          <a className="btn" href={broadcastHref} target="_blank" rel="noreferrer">{t(lang, 'broadcastLink')}</a>
        </div>
      </header>

      <main className="grid">
        <div className="main-col">
          {route.split ? (
            <div className="split">
              <Screen replay={replay} ms={ms} msRef={msRef} profile={profile} evidenceMoment={showOnPitch ? selected : null} onWhy={pick} overlays={overlays} title={`${t(lang, profile.mode)} · ${profile.language.toUpperCase()}`} />
              <Screen replay={replay} ms={ms} msRef={msRef} profile={profileB} evidenceMoment={showOnPitch ? selected : null} onWhy={pick} overlays={overlays} title={`${t(profileB.language, profileB.mode)} · ${profileB.language.toUpperCase()}`} />
            </div>
          ) : (
            <Screen replay={replay} ms={ms} msRef={msRef} profile={profile} evidenceMoment={showOnPitch ? selected : null} onWhy={pick} overlays={overlays} />
          )}
          <Transport replay={replay} ms={ms} playing={playing} speed={speed} lang={lang} toggle={toggle} setSpeed={setSpeed} seek={seek} onPick={pick} />
          <Timeline replay={replay} ms={ms} lang={lang} seek={seek} onPick={pick} selected={selected} />
        </div>
        <aside className="side-col">
          <ProfilePanel profile={profile} onChange={setProfile} replay={replay} heading={route.split ? `${t(lang, 'viewer')} A` : undefined} />
          {route.split && <ProfilePanel profile={profileB} onChange={setProfileB} replay={replay} heading={`${t(lang, 'viewer')} B`} />}
          <RecapPanel replay={replay} profile={profile} ms={ms} onPick={pick} />
          <section className="panel">
            <h2 className="panel-title">{t(lang, 'moments')}</h2>
            <MomentList replay={replay} lang={lang} selected={selected} onPick={pick} />
          </section>
        </aside>
      </main>

      <EvidenceDrawer moment={moment} replay={replay} lang={lang} onClose={() => setSelected(null)} onSeek={seek} showOnPitch={showOnPitch} setShowOnPitch={setShowOnPitch} health={health} />
      <footer className="foot">
        <span>{t(lang, 'synthetic')}</span>
        <span>{t(lang, 'poweredBy')}</span>
      </footer>
    </div>
  )
}

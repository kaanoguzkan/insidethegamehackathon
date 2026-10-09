import { useCallback, useEffect, useState } from 'react'
import { DEFAULT_PROFILE, type Lang, type Mode, type Profile } from '../lib/types'
import { CAMS, type Cam } from '../lib/webgl'

export interface Route {
  view: 'center' | 'broadcast'
  match: string | null
  profile: Profile
  split: boolean
  t: number | null
  step: Step
  tab: string | null // the open view in the Explore workspace
  cam: Cam | null // the pitch view: '2d' or a 3D camera; null picks 3D on a big screen and 2D on a phone
  follow: boolean // the 3D camera follows the ball
}

/** Watch the match, Understand why it happened, Explore the numbers: the three depths of the app. */
export type Step = 'watch' | 'understand' | 'explore'
export const STEPS: Step[] = ['watch', 'understand', 'explore']

const LANGS: Lang[] = ['en', 'es', 'tr']

export function parseHash(hash: string): Route {
  const [path, query = ''] = hash.replace(/^#/, '').split('?')
  const q = new URLSearchParams(query)
  const lang = q.get('lang') as Lang | null
  const mode = q.get('mode') as Mode | null
  const broadcast = path.startsWith('/broadcast')
  const profile: Profile = {
    ...DEFAULT_PROFILE,
    language: lang && LANGS.includes(lang) ? lang : DEFAULT_PROFILE.language,
    mode: mode === 'analyst' || mode === 'casual' ? mode : DEFAULT_PROFILE.mode,
    perspective: q.get('club') || 'neutral',
    focusPlayer: q.get('focus') || null,
    // The overlay-only page is a clean feed: nothing but graphics that are due. Its default is low density, which hides the always-on
    // meters (the momentum bar); `density=medium` brings them back.
    density: (['low', 'medium', 'high'] as const).find((d) => d === q.get('density')) ?? (broadcast ? 'low' : DEFAULT_PROFILE.density),
    audioDescribed: q.get('aria') === '1',
    reducedMotion: q.get('motion') === '0',
    highContrast: q.get('hc') === '1',
  }
  const t = q.get('t')
  const step = STEPS.find((x) => x === q.get('step')) ?? 'watch'
  return {
    view: broadcast ? 'broadcast' : 'center',
    match: q.get('match'),
    profile,
    split: q.get('split') === '1',
    t: t ? Number(t) * 60_000 : null,
    step,
    tab: q.get('tab'),
    cam: CAMS.find((c) => c === q.get('cam')) ?? null,
    follow: q.get('follow') === '1',
  }
}

export function buildHash(r: Omit<Route, 't'> & { t?: number | null }): string {
  const q = new URLSearchParams()
  if (r.match) q.set('match', r.match)
  q.set('mode', r.profile.mode)
  q.set('lang', r.profile.language)
  if (r.profile.perspective !== 'neutral') q.set('club', r.profile.perspective)
  if (r.profile.focusPlayer) q.set('focus', r.profile.focusPlayer)
  if (r.profile.density !== (r.view === 'broadcast' ? 'low' : 'medium')) q.set('density', r.profile.density) // only what differs from the page's default
  if (r.profile.audioDescribed) q.set('aria', '1')
  if (r.profile.reducedMotion) q.set('motion', '0')
  if (r.profile.highContrast) q.set('hc', '1')
  if (r.split) q.set('split', '1')
  if (r.step !== 'watch') q.set('step', r.step)
  if (r.step === 'explore' && r.tab) q.set('tab', r.tab)
  if (r.cam) q.set('cam', r.cam)
  if (r.follow) q.set('follow', '1')
  return `#/${r.view === 'broadcast' ? 'broadcast' : ''}?${q.toString()}`
}

/** The whole view state lives in the URL hash, so any view is shareable and refresh-safe. */
export function useRoute(): [Route, (patch: Partial<Route>) => void] {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash))
  useEffect(() => {
    const on = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  const update = useCallback((patch: Partial<Route>) => {
    const next = { ...parseHash(window.location.hash), ...patch }
    window.history.replaceState(null, '', buildHash(next))
    setRoute({ ...next })
  }, [])
  return [route, update]
}

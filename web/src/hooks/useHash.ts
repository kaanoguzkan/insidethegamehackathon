import { useCallback, useEffect, useState } from 'react'
import { DEFAULT_PROFILE, type Lang, type Mode, type Profile } from '../lib/types'

export interface Route {
  view: 'center' | 'broadcast'
  match: string | null
  profile: Profile
  split: boolean
  t: number | null
  step: Step
  tab: string | null // the open view in the Explore workspace
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
  const profile: Profile = {
    ...DEFAULT_PROFILE,
    language: lang && LANGS.includes(lang) ? lang : DEFAULT_PROFILE.language,
    mode: mode === 'analyst' || mode === 'casual' ? mode : DEFAULT_PROFILE.mode,
    perspective: q.get('club') || 'neutral',
    focusPlayer: q.get('focus') || null,
    density: (['low', 'medium', 'high'] as const).find((d) => d === q.get('density')) ?? DEFAULT_PROFILE.density,
    audioDescribed: q.get('aria') === '1',
    reducedMotion: q.get('motion') === '0',
    highContrast: q.get('hc') === '1',
  }
  const t = q.get('t')
  const step = STEPS.find((x) => x === q.get('step')) ?? 'watch'
  return {
    view: path.startsWith('/broadcast') ? 'broadcast' : 'center',
    match: q.get('match'),
    profile,
    split: q.get('split') === '1',
    t: t ? Number(t) * 60_000 : null,
    step,
    tab: q.get('tab'),
  }
}

export function buildHash(r: Omit<Route, 't'> & { t?: number | null }): string {
  const q = new URLSearchParams()
  if (r.match) q.set('match', r.match)
  q.set('mode', r.profile.mode)
  q.set('lang', r.profile.language)
  if (r.profile.perspective !== 'neutral') q.set('club', r.profile.perspective)
  if (r.profile.focusPlayer) q.set('focus', r.profile.focusPlayer)
  if (r.profile.density !== 'medium') q.set('density', r.profile.density)
  if (r.profile.audioDescribed) q.set('aria', '1')
  if (r.profile.reducedMotion) q.set('motion', '0')
  if (r.profile.highContrast) q.set('hc', '1')
  if (r.split) q.set('split', '1')
  if (r.step !== 'watch') q.set('step', r.step)
  if (r.step === 'explore' && r.tab) q.set('tab', r.tab)
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

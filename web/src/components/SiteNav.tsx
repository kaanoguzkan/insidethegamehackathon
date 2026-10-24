import { t } from '../i18n'
import type { Lang } from '../lib/types'

export type NavKey = 'live' | 'replay' | 'ask' | 'pipeline' | 'ops' | 'architecture'

interface Props {
  lang: Lang
  active: NavKey
  /** In the match center the first three act on the page; elsewhere they are links back to it. */
  onLive?: () => void
  onReplay?: () => void
  onAsk?: () => void
  liveAvailable?: boolean
}

const LINKS: Record<NavKey, string> = { live: '#/?go=live', replay: '#/', ask: '#/?go=ask', pipeline: '#pipeline', ops: '#ops', architecture: '#architecture' }
const LABELS: Record<NavKey, string> = { live: 'nav.live', replay: 'nav.replay', ask: 'nav.ask', pipeline: 'nav.pipeline', ops: 'nav.ops', architecture: 'nav.arch' }
const ORDER: NavKey[] = ['live', 'replay', 'ask', 'pipeline', 'ops', 'architecture']

/** The one menu of the site: the same six places on every page, each one click away. */
export function SiteNav({ lang, active, onLive, onReplay, onAsk, liveAvailable = true }: Props) {
  const act: Partial<Record<NavKey, (() => void) | undefined>> = { live: onLive, replay: onReplay, ask: onAsk }
  return (
    <nav className="sitenav" aria-label="Rifinitore">
      {ORDER.filter((k) => k !== 'live' || liveAvailable).map((k) => {
        const cls = `nav-item${active === k ? ' on' : ''}${k === 'live' ? ' is-live' : ''}`
        const label = (
          <>
            {k === 'live' && <span className="live-dot" aria-hidden="true" />}
            {t(lang, LABELS[k])}
          </>
        )
        const handler = act[k]
        return handler ? (
          <button key={k} type="button" className={cls} aria-current={active === k ? 'page' : undefined} onClick={handler}>{label}</button>
        ) : (
          <a key={k} className={cls} href={LINKS[k]} aria-current={active === k ? 'page' : undefined}>{label}</a>
        )
      })}
    </nav>
  )
}

/** The logo and name, linking to the start page. */
export function Brand({ lang, onClick }: { lang: Lang; onClick?: () => void }) {
  const inner = (
    <>
      <svg width="24" height="24" viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="10" fill="none" stroke="currentColor" strokeWidth="3" /><circle cx="16" cy="16" r="3" fill="currentColor" /></svg>
      <b>{t(lang, 'appTitle')}</b>
    </>
  )
  return onClick ? (
    <button type="button" className="brand brand-btn" onClick={onClick} title={t(lang, 'nav.home')}>{inner}</button>
  ) : (
    <a className="brand brand-btn" href="#/" title={t(lang, 'nav.home')}>{inner}</a>
  )
}

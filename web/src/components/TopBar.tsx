import type { Lang } from '../lib/types'
import { Brand, type NavKey, SiteNav } from './SiteNav'

interface Props {
  lang: Lang
  active: NavKey
  onHome?: () => void
  onLive?: () => void
  onReplay?: () => void
  onAsk?: () => void
  liveAvailable?: boolean
}

/**
 * The top bar of the whole site. One component, one place, the same on every page: the brand, the one menu and the repository link.
 * What belongs to a single page (the match picker, the viewer, the tools) is not here: it sits in that page's own toolbar under this bar.
 */
export function TopBar({ lang, active, onHome, onLive, onReplay, onAsk, liveAvailable }: Props) {
  return (
    <header className="topbar">
      <Brand lang={lang} onClick={onHome} />
      <SiteNav lang={lang} active={active} liveAvailable={liveAvailable} onLive={onLive} onReplay={onReplay} onAsk={onAsk} />
      <a className="tb-link" href="https://github.com/kaanoguzkan/insidethegamehackathon" target="_blank" rel="noreferrer">GitHub</a>
    </header>
  )
}

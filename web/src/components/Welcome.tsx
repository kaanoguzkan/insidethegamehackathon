import { t } from '../i18n'
import type { Lang } from '../lib/types'

interface Props {
  lang: Lang
  onPlay: () => void
  onLive?: () => void
  onSkip: () => void
}

/** What a first-time visitor sees on the stage: what this is, and the three things to try. Dismissed once and remembered. */
export function Welcome({ lang, onPlay, onLive, onSkip }: Props) {
  return (
    <div className="welcome" role="dialog" aria-modal="false" aria-label={t(lang, 'welcome.title')}>
      <div className="welcome-card">
        <h2>{t(lang, 'welcome.title')}</h2>
        <p>{t(lang, 'welcome.body')}</p>
        <ul>
          <li>{t(lang, 'welcome.li1')}</li>
          <li>{t(lang, 'welcome.li2')}</li>
          {onLive && <li>{t(lang, 'welcome.li3')}</li>}
        </ul>
        <div className="welcome-actions">
          <button type="button" className="btn primary" onClick={onPlay} autoFocus>{t(lang, 'welcome.play')}</button>
          {onLive && <button type="button" className="btn" onClick={onLive}>{t(lang, 'welcome.live')}</button>}
          <button type="button" className="btn" onClick={onSkip}>{t(lang, 'welcome.skip')}</button>
        </div>
      </div>
    </div>
  )
}

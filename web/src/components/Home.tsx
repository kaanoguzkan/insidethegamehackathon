import { t } from '../i18n'
import type { Lang, Mode, Profile } from '../lib/types'

interface Props {
  lang: Lang
  profile: Profile
  onProfile: (p: Partial<Profile>) => void
  /** Undefined when there is no Brain to ask (the static mirror): the live and Ask cards are then left out. */
  onLive?: () => void
  onAsk?: () => void
  onReplay: () => void
  onSkip: () => void
}

/** The start page: the things worth doing, each one click away, before anything else. */
export function Home({ lang, profile, onProfile, onLive, onAsk, onReplay, onSkip }: Props) {
  const modes: Mode[] = ['casual', 'analyst']
  return (
    <div className="welcome startpage" role="dialog" aria-modal="false" aria-label={t(lang, 'welcome.title')}>
      <div className="home-inner">
        <h2>{t(lang, 'welcome.title')}</h2>
        <p className="home-lead">{t(lang, 'welcome.body')}</p>
        <div className="home-grid">
          {onLive && (
            <section className="home-card prime">
              <h3><span className="live-dot" aria-hidden="true" />{t(lang, 'home.live.t')}</h3>
              <p>{t(lang, 'home.live.d')}</p>
              <button type="button" className="btn live-cta" onClick={onLive} autoFocus><span className="live-dot" aria-hidden="true" />{t(lang, 'welcome.live')}</button>
            </section>
          )}
          <section className="home-card">
            <h3>{t(lang, 'home.replay.t')}</h3>
            <p>{t(lang, 'home.replay.d')}</p>
            <button type="button" className={`btn${onLive ? '' : ' primary'}`} onClick={onReplay} autoFocus={!onLive}>{t(lang, 'welcome.play')}</button>
          </section>
          {onAsk && (
            <section className="home-card">
              <h3>{t(lang, 'home.ask.t')}</h3>
              <p>{t(lang, 'home.ask.d')}</p>
              <button type="button" className="btn" onClick={onAsk}>{t(lang, 'nav.ask')}</button>
            </section>
          )}
          <section className="home-card">
            <h3>{t(lang, 'home.viewer.t')}</h3>
            <p>{t(lang, 'home.viewer.d')}</p>
            <div className="chips" role="group" aria-label={t(lang, 'home.viewer.t')}>
              {modes.map((m) => <button key={m} type="button" className={`chip${profile.mode === m ? ' on' : ''}`} aria-pressed={profile.mode === m} onClick={() => onProfile({ mode: m })}>{t(lang, `home.mode.${m}`)}</button>)}
              {(['en', 'es', 'tr'] as const).map((l) => <button key={l} type="button" className={`chip${profile.language === l ? ' on' : ''}`} aria-pressed={profile.language === l} onClick={() => onProfile({ language: l })}>{l.toUpperCase()}</button>)}
            </div>
          </section>
          <section className="home-card">
            <h3>{t(lang, 'home.under.t')}</h3>
            <p>{t(lang, 'home.under.d')}</p>
            <div className="chips">
              <a className="btn" href="#pipeline">{t(lang, 'nav.pipeline')}</a>
              <a className="btn" href="#ops">{t(lang, 'nav.ops')}</a>
              <a className="btn" href="#architecture">{t(lang, 'nav.arch')}</a>
            </div>
          </section>
        </div>
        <button type="button" className="home-skip" onClick={onSkip}>{t(lang, 'home.skip')}</button>
      </div>
    </div>
  )
}

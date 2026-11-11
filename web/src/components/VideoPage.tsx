import { t } from '../i18n'
import { TopBar } from './TopBar'

const VIDEO_ID = 'IcC8Hgkt26s'

/** The demo video, for the build that has no Brain behind it (the portfolio mirror): what the live features looked like while they ran. */
export function VideoPage() {
  const lang = 'en'
  return (
    <>
      <TopBar lang={lang} active="video" />
      <main className="ops arch">
        <header>
          <h1>{t(lang, 'video.h')}</h1>
          <p className="muted">{t(lang, 'video.lead')}</p>
          <p className="muted">{t(lang, 'static.note')}</p>
        </header>
        <div style={{ position: 'relative', paddingBottom: '56.25%', height: 0, maxWidth: 1100, borderRadius: 12, overflow: 'hidden' }}>
          <iframe
            style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', border: 0 }}
            src={`https://www.youtube-nocookie.com/embed/${VIDEO_ID}`}
            title="Rifinitore demo video"
            allow="accelerometer; encrypted-media; picture-in-picture; fullscreen"
            allowFullScreen
            loading="lazy"
          />
        </div>
        <p>
          <a className="btn" href={`https://www.youtube.com/watch?v=${VIDEO_ID}`} target="_blank" rel="noreferrer">YouTube</a>{' '}
          <a className="btn" href="https://github.com/kaanoguzkan/insidethegamehackathon" target="_blank" rel="noreferrer">{t(lang, 'video.code')}</a>{' '}
          <a className="btn" href="#architecture">{t(lang, 'nav.arch')}</a>{' '}
          <a className="btn" href="#/">{t(lang, 'nav.replay')}</a>
        </p>
      </main>
    </>
  )
}

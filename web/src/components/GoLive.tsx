import { useState } from 'react'
import { t } from '../i18n'
import { startStream, STREAM_SPEEDS, StreamBusy, StreamRate } from '../lib/stream'
import type { Cohort, Lang } from '../lib/types'
import { Popover } from './Popover'

interface Props {
  lang: Lang
  /** The demo to play (a replay's id is its demo's id) and the viewers to write the story for. */
  demo: string
  cohorts: Cohort[]
  onStarted: (streamId: string) => void
}

/** The button that plays the open match live: pick a speed, kick off. */
export function GoLive({ lang, demo, cohorts, onStarted }: Props) {
  const [speed, setSpeed] = useState<number>(5)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const go = async () => {
    setBusy(true)
    setError(null)
    try {
      const s = await startStream(demo, speed, cohorts)
      onStarted(s.streamId)
    } catch (e) {
      setError(t(lang, e instanceof StreamBusy ? 'stream.busy' : e instanceof StreamRate ? 'stream.rate' : 'stream.failed'))
      setBusy(false)
    }
  }

  return (
    <Popover label={<><span className="live-dot" aria-hidden="true" />{t(lang, 'stream.go')}</>} title={t(lang, 'stream.title')} className="live-pop">
      <p className="pop-title">{t(lang, 'stream.title')}</p>
      <p className="hint">{t(lang, 'stream.hint')}</p>
      <div className="seg" role="radiogroup" aria-label={t(lang, 'stream.speed')}>
        {STREAM_SPEEDS.map((v) => (
          <button key={v} type="button" role="radio" aria-checked={speed === v} className={speed === v ? 'on' : ''} onClick={() => setSpeed(v)}>
            {v}×
          </button>
        ))}
      </div>
      <button type="button" className="btn wide primary" disabled={busy} onClick={() => void go()}>
        {t(lang, busy ? 'stream.starting' : 'stream.start')}
      </button>
      {error && <p className="hint" role="alert">{error}</p>}
    </Popover>
  )
}

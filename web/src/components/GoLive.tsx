import { useState } from 'react'
import { t } from '../i18n'
import { startStream, STREAM_SPEEDS, STREAM_STARTS, StreamBusy, StreamRate } from '../lib/stream'
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
  const [from, setFrom] = useState<number>(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const go = async () => {
    setBusy(true)
    setError(null)
    try {
      const s = await startStream(demo, speed, cohorts, from)
      onStarted(s.streamId)
    } catch (e) {
      setError(t(lang, e instanceof StreamBusy ? 'stream.busy' : e instanceof StreamRate ? 'stream.rate' : 'stream.failed'))
      setBusy(false)
    }
  }

  return (
    <div className="golive">
      <button type="button" className="btn live-cta" disabled={busy} onClick={() => void go()} title={t(lang, 'stream.hint')}>
        <span className="live-dot" aria-hidden="true" />
        {t(lang, busy ? 'stream.starting' : 'stream.go')}
      </button>
      <Popover label={<span aria-hidden="true">⚙</span>} title={t(lang, 'stream.title')} className="live-pop">
        <p className="pop-title">{t(lang, 'stream.title')}</p>
        <p className="hint">{t(lang, 'stream.hint')}</p>
        <div className="seg" role="radiogroup" aria-label={t(lang, 'stream.speed')}>
          {STREAM_SPEEDS.map((v) => (
            <button key={v} type="button" role="radio" aria-checked={speed === v} className={speed === v ? 'on' : ''} onClick={() => setSpeed(v)}>
              {v}×
            </button>
          ))}
        </div>
        <div className="seg" role="radiogroup" aria-label={t(lang, 'stream.from')}>
          {STREAM_STARTS.map((v) => (
            <button key={v} type="button" role="radio" aria-checked={from === v} className={from === v ? 'on' : ''} onClick={() => setFrom(v)}>
              {v === 0 ? t(lang, 'stream.kickoff') : `${v}'`}
            </button>
          ))}
        </div>
      </Popover>
      {error && <span className="hint golive-error" role="alert">{error}</span>}
    </div>
  )
}

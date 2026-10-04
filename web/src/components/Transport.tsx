import { t } from '../i18n'
import { clockAt, totalMs } from '../lib/clock'
import type { Replay } from '../lib/data'
import type { Lang } from '../lib/types'

const SPEEDS = [1, 5, 10, 30, 60]

interface Props {
  replay: Replay
  ms: number
  playing: boolean
  speed: number
  lang: Lang
  toggle: () => void
  setSpeed: (s: number) => void
  seek: (ms: number) => void
  onPick: (momentId: string) => void
}

export function Transport({ replay, ms, playing, speed, lang, toggle, setSpeed, seek, onPick }: Props) {
  const total = totalMs(replay.meta)
  const p2 = replay.meta.periods.find((p) => p.period === 2)
  return (
    <div className="transport">
      <button type="button" className="play" onClick={toggle} aria-label={playing ? t(lang, 'pause') : t(lang, 'play')} title="Space">
        {playing ? (
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><rect x="3" y="2" width="4" height="14" rx="1" /><rect x="11" y="2" width="4" height="14" rx="1" /></svg>
        ) : (
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><path d="M4 2.5v13l11-6.5z" /></svg>
        )}
      </button>
      <div className="scrub">
        <div className="ticks" aria-hidden={false}>
          {replay.moments
            .filter((m) => m.salience >= 0.45)
            .map((m) => (
              <button
                key={m.id}
                type="button"
                className={`tick type-${m.type}`}
                style={{ left: `${(m.detectedAt.matchMs / total) * 100}%` }}
                title={`${m.detectedAt.label} ${m.type.replace(/_/g, ' ')}`}
                aria-label={`${m.detectedAt.label} ${m.type.replace(/_/g, ' ')}`}
                onClick={() => onPick(m.id)}
              />
            ))}
          {p2 && <i className="half" style={{ left: `${(p2.startMs / total) * 100}%` }} />}
        </div>
        <input
          type="range"
          min={0}
          max={total}
          step={1000}
          value={ms}
          onChange={(e) => seek(Number(e.target.value))}
          aria-label={t(lang, 'jump')}
          aria-valuetext={clockAt(replay.meta, ms).label}
        />
      </div>
      <time className="clock-label">{clockAt(replay.meta, ms).label}</time>
      <label className="speed">
        <span>{t(lang, 'speed')}</span>
        <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
          {SPEEDS.map((s) => (
            <option key={s} value={s}>{s}×</option>
          ))}
        </select>
      </label>
    </div>
  )
}

import { useRef, type CSSProperties } from 'react'
import { t } from '../i18n'
import type { WinPoint } from '../lib/analytics'
import { clockAt, totalMs } from '../lib/clock'
import type { Replay } from '../lib/data'
import { LAYER_KEYS, type Layers } from '../lib/layers'
import type { Lang } from '../lib/types'
import { Popover } from './Popover'

const SPEEDS = [1, 5, 10, 30, 60]
const VB = 1000
const ROW = 20 // px per story row

const TYPE_COLOR: Record<string, string> = {
  goal: 'var(--good)', red_card: 'var(--bad)', penalty: 'var(--warn)', big_chance: 'var(--gold)',
  pressure_collapse: '#7fb4ff', pressure_surge: '#7fb4ff', momentum_swing: '#b794f6',
  chaos_flip: 'var(--muted)', rhythm_break: 'var(--muted)', tactical_shift: 'var(--muted)', fatigue_drop: 'var(--muted)', physical_highlight: 'var(--muted)',
}

interface Props {
  replay: Replay
  ms: number
  playing: boolean
  speed: number
  lang: Lang
  layers: Layers
  selected: string | null
  toggle: () => void
  setSpeed: (s: number) => void
  seek: (ms: number) => void
  onPick: (momentId: string) => void
  onLayer: (k: (typeof LAYER_KEYS)[number]) => void
  onClearLayers: () => void
}

/**
 * Everything about time in one place: play, speed, the pitch lenses, and a story ribbon you can drag.
 * The ribbon stacks win probability, momentum, chaos and pressure so the shape of the match is visible at a glance.
 */
export function MatchStrip({ replay, ms, playing, speed, lang, layers, selected, toggle, setSpeed, seek, onPick, onLayer, onClearLayers }: Props) {
  const total = totalMs(replay.meta)
  const { home, away } = replay.meta
  const snaps = replay.snapshots
  const series = replay.analytics?.winProbability.series ?? []
  const p2 = replay.meta.periods.find((p) => p.period === 2)
  const track = useRef<HTMLDivElement>(null)
  const x = (v: number) => (v / total) * VB
  const rowY = (row: number, v: number) => row * ROW + 2 + (1 - v) * (ROW - 4) // v in 0..1, 1 = top of the row

  const winRow = () => {
    if (!series.length) return null
    const share = (p: WinPoint['p']) => p.home + p.draw / 2
    const pts = series.map((s) => `${x(s.matchMs).toFixed(1)} ${rowY(0, share(s.p)).toFixed(1)}`)
    const base = `${x(series[series.length - 1].matchMs).toFixed(1)} ${ROW - 2} ${x(series[0].matchMs).toFixed(1)} ${ROW - 2}`
    return `M${pts.join(' L')} L${base} Z`
  }
  const lineOf = (row: number, get: (s: (typeof snaps)[number]) => number, lo: number, hi: number) =>
    snaps.map((s, i) => `${i ? 'L' : 'M'}${x(s.matchMs).toFixed(1)} ${rowY(row, (get(s) - lo) / (hi - lo)).toFixed(1)}`).join(' ')
  const momentum = (above: boolean) => {
    const mid = ROW + ROW / 2
    const pts = snaps.map((s) => {
      const d = (s.momentum[home.id] - 0.5) * (ROW - 4)
      return `${x(s.matchMs).toFixed(1)} ${(mid - (above ? Math.max(0, d) : Math.min(0, d))).toFixed(1)}`
    })
    return pts.length ? `M${x(snaps[0].matchMs)} ${mid} L${pts.join(' L')} L${x(snaps[snaps.length - 1].matchMs)} ${mid} Z` : ''
  }

  const seekTo = (clientX: number) => {
    const r = track.current!.getBoundingClientRect()
    seek(Math.max(0, Math.min(total, ((clientX - r.left) / r.width) * total)))
  }
  const rows = [t(lang, 'winShort'), t(lang, 'momentum'), t(lang, 'chaos'), t(lang, 'pressure')]
  const active = LAYER_KEYS.filter((k) => layers[k]).length
  const clock = clockAt(replay.meta, ms)
  const H = ROW * rows.length

  return (
    <section className="strip" aria-label={t(lang, 'matchControls')}>
      <div className="strip-controls">
        <button type="button" className="play" onClick={toggle} aria-label={playing ? t(lang, 'pause') : t(lang, 'play')} title="Space">
          {playing ? (
            <svg width="16" height="16" viewBox="0 0 18 18" aria-hidden="true"><rect x="3" y="2" width="4" height="14" rx="1" /><rect x="11" y="2" width="4" height="14" rx="1" /></svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 18 18" aria-hidden="true"><path d="M4 2.5v13l11-6.5z" /></svg>
          )}
        </button>
        <time className="clock-label">{clock.label}</time>
        <label className="speed">
          <span className="sr-only">{t(lang, 'speed')}</span>
          <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} aria-label={t(lang, 'speed')}>
            {SPEEDS.map((s) => (
              <option key={s} value={s}>{s}×</option>
            ))}
          </select>
        </label>
        <Popover
          label={t(lang, 'lenses')}
          title={t(lang, 'lensesTitle')}
          align="start"
          placement="above"
          badge={active > 0 ? <b className="count">{active}</b> : null}
        >
          <p className="pop-title">{t(lang, 'lensesTitle')}</p>
          <ul className="lens-list">
            {LAYER_KEYS.map((k) => (
              <li key={k}>
                <label>
                  <input type="checkbox" checked={layers[k]} onChange={() => onLayer(k)} />
                  <span><b>{t(lang, `layer.${k}`)}</b><small>{t(lang, `lens.${k}`)}</small></span>
                </label>
              </li>
            ))}
          </ul>
          {active > 0 && <button type="button" className="btn quiet" onClick={onClearLayers}>{t(lang, 'clearLenses')}</button>}
        </Popover>
      </div>

      <div
        ref={track}
        className="ribbon"
        style={{ '--rows': rows.length } as CSSProperties}
        role="slider"
        tabIndex={0}
        aria-label={t(lang, 'jump')}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={Math.round(ms)}
        aria-valuetext={clock.label}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId)
          seekTo(e.clientX)
        }}
        onPointerMove={(e) => e.buttons === 1 && seekTo(e.clientX)}
      >
        <div className="rb-markers">
          {replay.moments
            .filter((m) => m.salience >= 0.45)
            .map((m) => (
              <button
                key={m.id}
                type="button"
                className={`rb-marker${m.id === selected ? ' on' : ''}`}
                style={{ left: `${(m.detectedAt.matchMs / total) * 100}%`, background: TYPE_COLOR[m.type] ?? 'var(--muted)' }}
                title={`${m.detectedAt.label} ${m.type.replace(/_/g, ' ')}`}
                aria-label={`${m.detectedAt.label} ${m.type.replace(/_/g, ' ')}`}
                onPointerDown={(e) => e.stopPropagation()}
                onClick={() => onPick(m.id)}
              />
            ))}
        </div>
        <div className="rb-rows">
          <svg viewBox={`0 0 ${VB} ${H}`} preserveAspectRatio="none" aria-hidden="true">
            {rows.map((_, i) => (
              <rect key={i} x={0} y={i * ROW + 1} width={VB} height={ROW - 2} className="rb-bg" />
            ))}
            {series.length > 0 && (
              <>
                <rect x={0} y={2} width={VB} height={ROW - 4} fill={away.colors.primary} opacity="0.55" />
                <path d={winRow() ?? ''} fill={home.colors.primary} opacity="0.9" />
                <line x1={0} x2={VB} y1={rowY(0, 0.5)} y2={rowY(0, 0.5)} className="rb-mid" />
              </>
            )}
            <path d={momentum(true)} fill={home.colors.primary} opacity="0.9" />
            <path d={momentum(false)} fill={away.colors.primary} opacity="0.9" />
            <line x1={0} x2={VB} y1={ROW * 1.5} y2={ROW * 1.5} className="rb-mid" />
            <line x1={0} x2={VB} y1={rowY(2, 0.5)} y2={rowY(2, 0.5)} className="rb-mid" />
            <path d={lineOf(2, (s) => s.chaos, 0, 100)} className="rb-line" stroke="var(--gold)" />
            <path d={lineOf(3, (s) => s.pressure[home.id], 0, 100)} className="rb-line" stroke={home.colors.primary} />
            <path d={lineOf(3, (s) => s.pressure[away.id], 0, 100)} className="rb-line dashed" stroke={away.colors.primary} />
            {p2 && <line x1={x(p2.startMs)} x2={x(p2.startMs)} y1={0} y2={H} className="rb-half" />}
          </svg>
          <ul className="rb-labels" aria-hidden="true">
            {rows.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
        <div className="rb-head" style={{ left: `${(ms / total) * 100}%` }} />
      </div>
    </section>
  )
}

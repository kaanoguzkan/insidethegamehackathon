import { useRef, useState } from 'react'
import { t } from '../i18n'
import { winProbAt } from '../lib/analytics'
import { clockAt, totalMs } from '../lib/clock'
import type { Replay } from '../lib/data'
import { LAYER_KEYS, type Layers } from '../lib/layers'
import type { Lang } from '../lib/types'
import { Popover } from './Popover'

const SPEEDS = [1, 5, 10, 30, 60]
const VB = 1000
const ROW = 20 // viewBox units per story row (the pixel height comes from CSS)

const TYPE_COLOR: Record<string, string> = {
  goal: 'var(--good)', red_card: 'var(--bad)', penalty: 'var(--warn)', big_chance: 'var(--gold)',
  pressure_collapse: '#7fb4ff', pressure_surge: '#7fb4ff', momentum_swing: '#b794f6',
  chaos_flip: 'var(--muted)', rhythm_break: 'var(--muted)', tactical_shift: 'var(--muted)', fatigue_drop: 'var(--muted)', physical_highlight: 'var(--muted)',
}

/** Team colours are dark on a dark ground; lines and swatches use a lifted copy so they can be read. */
function lift(hex: string, amount = 0.45): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex)
  if (!m) return hex
  const n = parseInt(m[1], 16)
  const ch = (shift: number) => Math.round(((n >> shift) & 255) * (1 - amount) + 255 * amount)
  return `rgb(${ch(16)}, ${ch(8)}, ${ch(0)})`
}

const MINUTES = [15, 30, 45, 60, 75, 90]

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
  const [tall, setTall] = useState(false)
  const x = (v: number) => (v / total) * VB
  const rowY = (row: number, v: number) => row * ROW + 2 + (1 - v) * (ROW - 4) // v in 0..1, 1 = top of the row
  const homeLine = lift(home.colors.primary)
  const awayLine = lift(away.colors.primary)

  /** Home share at the bottom, away share at the top, the draw in between. */
  const winBand = (side: 'home' | 'away') => {
    if (!series.length) return ''
    const pts = series.map((s) => `${x(s.matchMs).toFixed(1)} ${(side === 'home' ? rowY(0, s.p.home) : rowY(0, 1 - s.p.away)).toFixed(1)}`)
    const edge = side === 'home' ? ROW - 2 : 2
    const first = x(series[0].matchMs).toFixed(1)
    const last = x(series[series.length - 1].matchMs).toFixed(1)
    return `M${first} ${edge} L${pts.join(' L')} L${last} ${edge} Z`
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

  // The numbers at the playhead, so each row says what it is showing right now.
  const snap = snaps.length ? snaps.reduce((best, s) => (Math.abs(s.matchMs - ms) < Math.abs(best.matchMs - ms) ? s : best), snaps[0]) : null
  const wp = winProbAt(replay.analytics, ms)
  const pc = (v: number) => `${Math.round(v * 100)}%`
  const swatch = (c: string) => <i className="sw" style={{ background: c }} aria-hidden="true" />
  const lanes: { label: string; value: React.ReactNode }[] = [
    { label: t(lang, 'winShort'), value: wp ? <>{swatch(homeLine)}{pc(wp.home)} {swatch('rgba(255,255,255,.55)')}{pc(wp.draw)} {swatch(awayLine)}{pc(wp.away)}</> : null },
    { label: t(lang, 'momentum'), value: snap ? <>{swatch(homeLine)}{pc(snap.momentum[home.id])} {swatch(awayLine)}{pc(snap.momentum[away.id])}</> : null },
    { label: t(lang, 'chaos'), value: snap ? <>{swatch('var(--gold)')}{Math.round(snap.chaos)}</> : null },
    { label: t(lang, 'pressure'), value: snap ? <>{swatch(homeLine)}{Math.round(snap.pressure[home.id])} {swatch(awayLine)}{Math.round(snap.pressure[away.id])}</> : null },
  ]
  const active = LAYER_KEYS.filter((k) => layers[k]).length
  const clock = clockAt(replay.meta, ms)
  const H = ROW * lanes.length
  // Minute marks follow the match clock: the second half restarts at 45' however much stoppage the first half had.
  const ticks = MINUTES.map((m) => ({ m, at: m <= 45 ? m * 60_000 : (p2?.startMs ?? 45 * 60_000) + (m - 45) * 60_000 })).filter((k) => k.at < total)

  return (
    <section className={`strip${tall ? ' tall' : ''}`} aria-label={t(lang, 'matchControls')}>
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
        <button type="button" className={`btn${tall ? ' on' : ''}`} aria-pressed={tall} onClick={() => setTall(!tall)} title={t(lang, 'stripTallerHint')}>
          {t(lang, tall ? 'stripShorter' : 'stripTaller')}
        </button>
      </div>

      <div className="ribbon-grid">
        <ul className="rb-gutter" aria-label={t(lang, 'timelines')}>
          <li className="lane-moments">{t(lang, 'rail.moments')}</li>
          {lanes.map((l) => (
            <li key={l.label} className="lane">
              <span className="rb-name">{l.label}</span>
              <span className="rb-val">{l.value}</span>
            </li>
          ))}
          <li className="lane-axis" aria-hidden="true" />
        </ul>

        <div
          ref={track}
          className="ribbon"
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
          <div className="rb-rows" style={{ ['--rows' as string]: lanes.length }}>
            <svg viewBox={`0 0 ${VB} ${H}`} preserveAspectRatio="none" aria-hidden="true">
              {lanes.map((_, i) => (
                <rect key={i} x={0} y={i * ROW + 1} width={VB} height={ROW - 2} className="rb-bg" />
              ))}
              {series.length > 0 && (
                <>
                  <rect x={0} y={2} width={VB} height={ROW - 4} fill="rgba(255,255,255,.16)" />
                  <path d={winBand('home')} fill={home.colors.primary} />
                  <path d={winBand('away')} fill={away.colors.primary} />
                  <line x1={0} x2={VB} y1={rowY(0, 0.5)} y2={rowY(0, 0.5)} className="rb-mid" />
                </>
              )}
              <path d={momentum(true)} fill={home.colors.primary} />
              <path d={momentum(false)} fill={away.colors.primary} />
              <line x1={0} x2={VB} y1={ROW * 1.5} y2={ROW * 1.5} className="rb-mid" />
              <line x1={0} x2={VB} y1={rowY(2, 0.5)} y2={rowY(2, 0.5)} className="rb-mid" />
              <path d={lineOf(2, (s) => s.chaos, 0, 100)} className="rb-line" stroke="var(--gold)" />
              <path d={lineOf(3, (s) => s.pressure[home.id], 0, 100)} className="rb-line" stroke={homeLine} />
              <path d={lineOf(3, (s) => s.pressure[away.id], 0, 100)} className="rb-line dashed" stroke={awayLine} />
              {p2 && <line x1={x(p2.startMs)} x2={x(p2.startMs)} y1={0} y2={H} className="rb-half" />}
              {ticks.map((k) => (
                <line key={k.m} x1={x(k.at)} x2={x(k.at)} y1={0} y2={H} className="rb-grid" />
              ))}
            </svg>
          </div>
          <div className="rb-axis" aria-hidden="true">
            {ticks.map((k) => (
              <span key={k.m} style={{ left: `${(k.at / total) * 100}%` }}>{k.m}&prime;</span>
            ))}
            {p2 && <span className="ht" style={{ left: `${(p2.startMs / total) * 100}%` }}>{t(lang, 'halfTime')}</span>}
          </div>
          <div className="rb-head" style={{ left: `${(ms / total) * 100}%` }} />
        </div>
      </div>
    </section>
  )
}

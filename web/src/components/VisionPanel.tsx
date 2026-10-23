import { useEffect, useRef, useState } from 'react'
import { t } from '../i18n'
import { BRAIN_URL } from '../lib/brain'
import type { Lang } from '../lib/types'

interface Stats {
  enabled: boolean
  frames?: number
  chunks?: number
  positionRmseCm?: number | null
  ballRmseCm?: number | null
  speedErrorKmh?: number | null
  identityKept?: number | null
  msPerChunk?: number | null
}

interface Props {
  lang: Lang
  streamId: string
  /** Where the picture is, in match ms: the frame shown is the one at that moment. */
  msRef: { current: number }
}

/**
 * The video feed the live match's physical analysis reads: the frame at the viewer's position with what the detector found boxed, and how close the tracking
 * it rebuilt from the pixels is to the truth. Without a video feed (the match was started without one) the card is not shown.
 */
export function VisionPanel({ lang, streamId, msRef }: Props) {
  const [stats, setStats] = useState<Stats | null>(null)
  const [src, setSrc] = useState<string | null>(null)
  const [open, setOpen] = useState(true)
  const url = useRef<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    const loadStats = () => void fetch(`${BRAIN_URL}/api/stream/${streamId}/vision`, { signal: ctl.signal }).then((r) => (r.ok ? r.json() : null)).then((s) => s && setStats(s as Stats)).catch(() => undefined)
    loadStats()
    const timer = setInterval(loadStats, 4000)
    return () => {
      ctl.abort()
      clearInterval(timer)
    }
  }, [streamId])

  useEffect(() => {
    if (!open || !stats?.enabled) return
    const ctl = new AbortController()
    const tick = async () => {
      try {
        const res = await fetch(`${BRAIN_URL}/api/stream/${streamId}/vision/frame?atMs=${Math.round(msRef.current)}`, { signal: ctl.signal })
        if (!res.ok) return
        const next = URL.createObjectURL(await res.blob())
        if (url.current) URL.revokeObjectURL(url.current)
        url.current = next
        setSrc(next)
      } catch {
        /* the next tick tries again */
      }
    }
    void tick()
    const timer = setInterval(tick, 1000)
    return () => {
      ctl.abort()
      clearInterval(timer)
    }
  }, [streamId, open, stats?.enabled, msRef])

  useEffect(() => () => { if (url.current) URL.revokeObjectURL(url.current) }, [])

  if (!stats?.enabled) return null
  return (
    <aside className={`vision${open ? '' : ' closed'}`} aria-label={t(lang, 'vision.title')}>
      <header>
        <b>{t(lang, 'vision.title')}</b>
        <button type="button" className="btn" onClick={() => setOpen((v) => !v)} aria-expanded={open}>{open ? '–' : '+'}</button>
      </header>
      {open && (
        <>
          {src ? <img src={src} alt={t(lang, 'vision.alt')} width={436} height={272} /> : <p className="hint">{t(lang, 'vision.wait')}</p>}
          <p className="vision-stats">
            {stats.positionRmseCm != null && <span>{t(lang, 'vision.players')} <b>{stats.positionRmseCm} cm</b></span>}
            {stats.ballRmseCm != null && <span>{t(lang, 'vision.ball')} <b>{stats.ballRmseCm} cm</b></span>}
            {stats.speedErrorKmh != null && <span>{t(lang, 'vision.speed')} <b>{stats.speedErrorKmh} km/h</b></span>}
            {stats.identityKept != null && <span>{t(lang, 'vision.ids')} <b>{Math.round(stats.identityKept * 100)}%</b></span>}
          </p>
          <p className="hint">{t(lang, 'vision.note')}</p>
        </>
      )}
    </aside>
  )
}

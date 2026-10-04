import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Playback clock for a recorded match. ``msRef`` is read by the canvas every animation frame;
 * ``ms`` is React state updated about 10 times a second for everything else (overlays, charts).
 */
export function useClock(totalMs: number, initialSpeed = 5) {
  const msRef = useRef(0)
  const [ms, setMs] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(initialSpeed)
  const speedRef = useRef(initialSpeed)
  speedRef.current = speed

  useEffect(() => {
    if (!playing) return
    let raf = 0
    let last = performance.now()
    let lastPush = 0
    const tick = (now: number) => {
      const dt = now - last
      last = now
      msRef.current = Math.min(totalMs, msRef.current + dt * speedRef.current)
      if (now - lastPush > 100) {
        lastPush = now
        setMs(msRef.current)
      }
      if (msRef.current >= totalMs) {
        setMs(msRef.current)
        setPlaying(false)
        return
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing, totalMs])

  const seek = useCallback(
    (to: number) => {
      msRef.current = Math.max(0, Math.min(totalMs, to))
      setMs(msRef.current)
    },
    [totalMs],
  )
  const toggle = useCallback(() => {
    if (msRef.current >= totalMs) {
      msRef.current = 0
      setMs(0)
    }
    setPlaying((p) => !p)
  }, [totalMs])

  return { ms, msRef, playing, setPlaying, speed, setSpeed, seek, toggle }
}

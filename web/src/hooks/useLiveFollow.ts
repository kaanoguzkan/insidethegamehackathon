import { useCallback, useEffect, useRef, useState } from 'react'
import type { StreamHandle } from './useStream'
import type { useClock } from './useClock'

/**
 * Keep the playback clock on the live picture (the feed less the broadcast delay) while the viewer is "following". Seeking, pausing or changing the speed detaches
 * the viewer (a rewind); ``goLive`` brings them back. The clock never runs ahead of the picture.
 */
/** A gap behind the picture up to this long is closed by playing faster for CATCH_UP_S seconds; a longer one is jumped. */
const CATCH_UP_MAX_MS = 120_000
const CATCH_UP_S = 6

export function useLiveFollow(live: StreamHandle | undefined, clock: ReturnType<typeof useClock>) {
  const [following, setFollowing] = useState(true)
  const { msRef, seek, setPlaying, setSpeed } = clock
  const catching = useRef(false) // playing faster than the match for a few seconds to close a gap that opened when the match slowed down
  const sessionSpeed = live?.speed ?? 1
  const holding = useRef(false) // paused for a moment because the picture is behind the clock (after a speed-up)

  useEffect(() => {
    if (!live) return
    setSpeed(sessionSpeed)
    setPlaying(true)
  }, [live?.id, sessionSpeed]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!live) return
    const timer = setInterval(() => {
      const target = live.playheadMs()
      // A faster match needs a longer lead (the delay is in wall seconds), so the picture steps back a little: wait for it, do not rewind.
      if (following && msRef.current > target + 1500) {
        if (!holding.current) { holding.current = true; setPlaying(false) }
        return
      }
      if (holding.current && msRef.current <= target + 300) { holding.current = false; setPlaying(true) }
      if (holding.current) return
      if (following) {
        const gap = target - msRef.current
        if (gap > 1500 && gap <= CATCH_UP_MAX_MS) {
          catching.current = true
          setSpeed(sessionSpeed + gap / 1000 / CATCH_UP_S) // close the gap in about CATCH_UP_S seconds: a quick run forward, not a jump
          return
        }
        if (catching.current) { catching.current = false; setSpeed(sessionSpeed) }
      }
      if (following ? Math.abs(msRef.current - target) > 1500 : msRef.current > target + 1500) {
        seek(target)
        if (!following) setFollowing(true) // caught up with the picture: that is live
      }
    }, 250)
    return () => clearInterval(timer)
  }, [live, following, seek, msRef, setPlaying, setSpeed, sessionSpeed])

  const detach = useCallback(() => setFollowing(false), [])
  const goLive = useCallback(() => {
    if (!live) return
    setFollowing(true)
    setSpeed(live.speed)
    setPlaying(true)
    seek(live.playheadMs())
  }, [live, seek, setPlaying, setSpeed])
  return { following, detach, goLive }
}

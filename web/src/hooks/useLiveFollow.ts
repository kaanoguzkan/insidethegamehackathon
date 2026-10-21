import { useCallback, useEffect, useState } from 'react'
import type { StreamHandle } from './useStream'
import type { useClock } from './useClock'

/**
 * Keep the playback clock on the live picture (the feed less the broadcast delay) while the viewer is "following". Seeking, pausing or changing the speed detaches
 * the viewer (a rewind); ``goLive`` brings them back. The clock never runs ahead of the picture.
 */
export function useLiveFollow(live: StreamHandle | undefined, clock: ReturnType<typeof useClock>) {
  const [following, setFollowing] = useState(true)
  const { msRef, seek, setPlaying, setSpeed } = clock
  const sessionSpeed = live?.speed ?? 1

  useEffect(() => {
    if (!live) return
    setSpeed(sessionSpeed)
    setPlaying(true)
  }, [live?.id, sessionSpeed]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!live) return
    const timer = setInterval(() => {
      const target = live.playheadMs()
      if (following ? Math.abs(msRef.current - target) > 1500 : msRef.current > target + 1500) {
        seek(target)
        if (!following) setFollowing(true) // caught up with the picture: that is live
      }
    }, 250)
    return () => clearInterval(timer)
  }, [live, following, seek, msRef])

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

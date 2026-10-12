import { type MutableRefObject, useEffect, useMemo, useState } from 'react'
import { BRAIN_URL } from '../lib/brain'
import { getChunk } from '../lib/live'
import { LiveTracking } from '../lib/tracking'

const AHEAD = 3 // chunks fetched ahead of the playing position
const CHUNK_MS = 5000

/**
 * Fetch the tracking chunks the pitch is about to need and add them to a :class:`LiveTracking`. The position it follows is the *playing* clock (behind the live
 * feed), so the chunk it asks for was published a while ago; one that is not there yet (404) is simply asked for again a moment later.
 */
export function useLiveTracking(matchId: string | null, playMsRef: MutableRefObject<number>, base = BRAIN_URL): { tracking: LiveTracking; ready: boolean } {
  const tracking = useMemo(() => new LiveTracking(), [matchId]) // eslint-disable-line react-hooks/exhaustive-deps
  const [ready, setReady] = useState(false)

  useEffect(() => {
    setReady(false)
    if (!matchId || !base) return
    const ctl = new AbortController()
    const asked = new Map<number, number>() // chunk -> wall time before which it is not asked for again
    const tick = async () => {
      const first = Math.max(0, Math.floor(playMsRef.current / CHUNK_MS) - 1)
      const now = Date.now()
      const todo = Array.from({ length: AHEAD + 2 }, (_, i) => first + i).filter((i) => !tracking.has(i) && (asked.get(i) ?? 0) <= now)
      await Promise.all(
        todo.map(async (i) => {
          asked.set(i, now + 20_000) // in flight: do not ask again meanwhile
          try {
            const c = await getChunk(matchId, i, base, ctl.signal)
            if (c) {
              tracking.addChunk(c)
              asked.delete(i)
              setReady(true)
            } else asked.set(i, Date.now() + 1500)
          } catch {
            asked.set(i, Date.now() + 3000)
          }
        }),
      )
    }
    void tick()
    const timer = setInterval(() => void tick(), 700)
    return () => {
      ctl.abort()
      clearInterval(timer)
    }
  }, [matchId, base, tracking, playMsRef])

  return { tracking, ready }
}

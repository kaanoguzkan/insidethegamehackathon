import { useEffect, useRef, useState } from 'react'
import { BRAIN_URL } from '../lib/brain'
import { getFeed, type LiveEvent, type LiveMatch, type LiveMoment, type LiveOverlay } from '../lib/live'

export interface LiveState {
  match: LiveMatch | null
  events: LiveEvent[]
  moments: LiveMoment[]
  overlays: LiveOverlay[]
  /** Wall time at which ``match.clockMs`` was read from the server, so the clock can run on between polls. */
  receivedAt: number
  error: string | null
}

const EMPTY: LiveState = { match: null, events: [], moments: [], overlays: [], receivedAt: 0, error: null }

/**
 * Follow a live match: poll the Brain's feed about once a second and keep what has arrived (events, moments, overlays). A viewer who joins late
 * pages through the past at once (the feed says ``more``); a Brain that is waking up simply answers late, and the loop carries on.
 */
export function useLiveFeed(matchId: string | null, base = BRAIN_URL): LiveState {
  const [state, setState] = useState<LiveState>(EMPTY)
  const cursors = useRef({ event: -1, since: 0 })

  useEffect(() => {
    setState(EMPTY)
    cursors.current = { event: -1, since: 0 }
    if (!matchId || !base) return
    const ctl = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    let finishedPolls = 0

    const tick = async () => {
      try {
        let more = true
        while (more && !ctl.signal.aborted) {
          const f = await getFeed(matchId, cursors.current.event, cursors.current.since, base, AbortSignal.any([ctl.signal, AbortSignal.timeout(30_000)]))
          cursors.current = { event: f.eventCursor, since: f.overlayCursor }
          more = f.more
          setState((s) => {
            const seen = new Set(s.events.map((e) => e.n))
            const overlays = new Map(s.overlays.map((o) => [o.id, o]))
            for (const o of f.overlays) overlays.set(o.id, o)
            const { events: _e, overlays: _o, moments: _m, eventCursor: _c, overlayCursor: _oc, more: _more, ...match } = f
            return {
              match,
              events: [...s.events, ...f.events.filter((e) => !seen.has(e.n))],
              moments: f.moments,
              overlays: [...overlays.values()],
              receivedAt: Date.now(),
              error: null,
            }
          })
          finishedPolls = f.status === 'finished' && !more && f.events.length === 0 && f.overlays.length === 0 ? finishedPolls + 1 : 0
        }
      } catch (e) {
        if (!ctl.signal.aborted) setState((s) => ({ ...s, error: (e as Error).message }))
      }
      if (!ctl.signal.aborted) timer = setTimeout(tick, finishedPolls > 3 ? 8000 : 1200)
    }
    void tick()
    return () => {
      ctl.abort()
      if (timer) clearTimeout(timer)
    }
  }, [matchId, base])

  return state
}

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BRAIN_URL } from '../lib/brain'
import type { Replay } from '../lib/data'
import { LiveTracking } from '../lib/tracking'
import type { Meta } from '../lib/types'
import {
  chunksDue, emptyStream, feedEdgeMs, getStreamChunk, getStreamFeed, getStreamMeta, mergeFeed, playheadMs, StreamGone, toReplay, type StreamData, type StreamSummary,
} from '../lib/stream'

export type StreamStatus = 'connecting' | 'live' | 'finished' | 'gone' | 'error'

export interface StreamHandle {
  id: string
  status: StreamStatus
  error: string | null
  /** The match as the match center reads it; null until the first answer. */
  replay: Replay | null
  summary: StreamSummary | null
  speed: number
  /** Match length, for the timeline's axis. */
  durationMs: number
  /** Where the feed stands, and where the picture should be (the feed less the broadcast delay), in match ms, read now. */
  edgeMs: () => number
  playheadMs: () => number
}

const POLL_MS = 700
const REBUILD_MS = 500

/**
 * Follow a match started with ``POST /api/stream``: poll its feed, keep the tracking chunks coming and present it all as a ``Replay`` that grows.
 * The replay object is rebuilt at most twice a second, and only when something arrived.
 */
export function useStream(streamId: string | null, base = BRAIN_URL): StreamHandle {
  const data = useRef<StreamData>(emptyStream())
  const metaRef = useRef<Meta | null>(null)
  const tracking = useMemo(() => new LiveTracking(), [streamId]) // eslint-disable-line react-hooks/exhaustive-deps
  const [status, setStatus] = useState<StreamStatus>('connecting')
  const [error, setError] = useState<string | null>(null)
  const [replay, setReplay] = useState<Replay | null>(null)
  const [summary, setSummary] = useState<StreamSummary | null>(null)
  const builtVersion = useRef(-1)

  const edgeMs = useCallback(() => {
    const d = data.current
    return d.summary ? feedEdgeMs(d.summary, d.receivedAt, Date.now()) : 0
  }, [])
  const head = useCallback(() => playheadMs(edgeMs(), data.current.summary?.speed ?? 1), [edgeMs])

  useEffect(() => {
    data.current = emptyStream()
    metaRef.current = null
    builtVersion.current = -1
    setStatus('connecting')
    setError(null)
    setReplay(null)
    setSummary(null)
    if (!streamId || !base) return
    const ctl = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    let finishedPolls = 0
    const asked = new Map<number, number>() // chunk -> wall time before which it is not asked for again

    const fetchChunks = async () => {
      const d = data.current
      if (!d.summary) return
      const due = chunksDue(edgeMs(), (i) => tracking.has(i) || (asked.get(i) ?? 0) > Date.now())
      await Promise.all(
        due.map(async (i) => {
          asked.set(i, Date.now() + 20_000)
          try {
            const c = await getStreamChunk(streamId, i, base, ctl.signal)
            if (c) {
              tracking.addChunk(c)
              asked.delete(i)
            } else asked.set(i, Date.now() + 800)
          } catch (e) {
            if (e instanceof StreamGone) throw e
            asked.set(i, Date.now() + 2500)
          }
        }),
      )
    }

    const tick = async () => {
      try {
        if (!metaRef.current) metaRef.current = await getStreamMeta(streamId, base, ctl.signal)
        let more = true
        while (more && !ctl.signal.aborted) {
          const f = await getStreamFeed(streamId, data.current.cursors, base, AbortSignal.any([ctl.signal, AbortSignal.timeout(20_000)]))
          mergeFeed(data.current, f, Date.now())
          more = f.more
        }
        await fetchChunks()
        const s = data.current.summary!
        setSummary((prev) => (prev && prev.status === s.status && prev.clockMs === s.clockMs ? prev : { ...s }))
        const st: StreamStatus = s.status === 'finished' ? 'finished' : s.status === 'failed' || s.status === 'stopped' ? 'gone' : 'live'
        setStatus(st)
        setError(null)
        finishedPolls = st === 'finished' ? finishedPolls + 1 : 0
        if (st === 'gone') return
      } catch (e) {
        if (ctl.signal.aborted) return
        if (e instanceof StreamGone) {
          setStatus('gone')
          return
        }
        setError((e as Error).message)
        setStatus((s) => (s === 'connecting' ? 'error' : s))
      }
      if (!ctl.signal.aborted) timer = setTimeout(tick, finishedPolls > 2 ? 4000 : POLL_MS)
    }
    void tick()

    const rebuild = setInterval(() => {
      const d = data.current
      if (!metaRef.current || !d.summary) return
      if (d.version === builtVersion.current && tracking.last === lastChunk.current) return
      builtVersion.current = d.version
      lastChunk.current = tracking.last
      setReplay(toReplay(streamId, metaRef.current, d, tracking))
    }, REBUILD_MS)
    const lastChunk = { current: -2 }

    return () => {
      ctl.abort()
      if (timer) clearTimeout(timer)
      clearInterval(rebuild)
    }
  }, [streamId, base, tracking, edgeMs])

  return { id: streamId ?? '', status, error, replay, summary, speed: summary?.speed ?? 1, durationMs: summary?.durationMs ?? 0, edgeMs, playheadMs: head }
}

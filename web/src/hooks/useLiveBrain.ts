import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BRAIN_URL, brainConfigured, cohortKey, type LiveResult, mergeLive, prewarm, requestBeats, wakeBrain } from '../lib/brain'
import type { Cohort, Overlay } from '../lib/types'

export type LiveStatus = 'off' | 'waking' | 'ready' | 'down'

export interface LiveBrain {
  available: boolean
  enabled: boolean
  status: LiveStatus
  busy: boolean
  error: string | null
  /** The newest live answer for the moment, if any. */
  resultFor: (momentId: string | null) => LiveResult | null
  toggle: () => void
  explain: (momentId: string, cohorts: Cohort[]) => void
  /** The recorded overlays with the live ones swapped in. */
  merge: (base: Overlay[]) => Overlay[]
}

/** Live answers from the Brain: off by default, and every failure leaves the recorded overlays in place. */
export function useLiveBrain(matchId: string): LiveBrain {
  const [enabled, setEnabled] = useState(false)
  const [status, setStatus] = useState<LiveStatus>('off')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<Map<string, LiveResult>>(new Map()) // moment id -> newest answer
  const asked = useRef(new Set<string>()) // "moment|cohorts" already requested for this match
  const ctl = useRef<AbortController | null>(null)

  useEffect(() => {
    if (brainConfigured) prewarm() // the page load wakes a scaled-to-zero service
  }, [])

  useEffect(() => {
    setResults(new Map())
    asked.current.clear()
    setError(null)
  }, [matchId])

  useEffect(() => {
    if (!enabled) return setStatus('off')
    const c = new AbortController()
    setStatus('waking')
    wakeBrain(BRAIN_URL, c.signal).then((up) => !c.signal.aborted && setStatus(up ? 'ready' : 'down'))
    return () => c.abort()
  }, [enabled])

  const explain = useCallback(
    (momentId: string, cohorts: Cohort[]) => {
      // Wait for the wake-up check: a request sent while a scaled-to-zero Brain is still starting would just time out.
      // The caller's effect runs again when the status becomes 'ready'.
      if (!enabled || status !== 'ready' || cohorts.length === 0) return
      const key = `${momentId}|${cohorts.map(cohortKey).sort().join(',')}`
      if (asked.current.has(key)) return
      asked.current.add(key)
      ctl.current?.abort()
      const c = (ctl.current = new AbortController())
      setBusy(true)
      setError(null)
      requestBeats(momentId, matchId, cohorts, BRAIN_URL, c.signal)
        .then((r) => {
          setStatus('ready')
          setResults((m) => new Map(m).set(momentId, { ...r, overlays: [...(m.get(momentId)?.overlays ?? []).filter((o) => !r.overlays.some((n) => n.id === o.id)), ...r.overlays] }))
        })
        .catch((e: Error) => {
          asked.current.delete(key)
          if (!c.signal.aborted) setError(e.message)
        })
        .finally(() => !c.signal.aborted && setBusy(false))
    },
    [enabled, status, matchId],
  )

  const resultFor = useCallback((momentId: string | null) => (momentId ? (results.get(momentId) ?? null) : null), [results])
  const merge = useCallback((base: Overlay[]) => (enabled ? mergeLive(base, results.values()) : base), [enabled, results])
  return useMemo(
    () => ({ available: brainConfigured, enabled, status, busy, error, resultFor, toggle: () => setEnabled((v) => !v), explain, merge }),
    [enabled, status, busy, error, resultFor, explain, merge],
  )
}

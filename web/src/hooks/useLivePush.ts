import { useEffect, useState } from 'react'
import type { LiveEvent, LiveMoment, LiveOverlay } from '../lib/live'

export type PushStatus = 'off' | 'connecting' | 'live' | 'down'

export type PushMessage =
  | { kind: 'overlays'; items: LiveOverlay[] }
  | { kind: 'moments'; items: LiveMoment[] }
  | { kind: 'events'; items: LiveEvent[] }

/**
 * Receive what the pipeline just stored, as it is stored, over Azure SignalR (through the Function app's negotiate endpoint). Without a push address, or
 * if the connection cannot be made, the status says so and the page keeps polling the feed: push only makes the page faster, never correct.
 */
export function useLivePush(matchId: string | null, pushUrl: string | null, onMessage: (m: PushMessage) => void): PushStatus {
  const [status, setStatus] = useState<PushStatus>('off')

  useEffect(() => {
    if (!matchId || !pushUrl) return setStatus('off')
    let stopped = false
    let stop: (() => Promise<void>) | null = null
    setStatus('connecting')
    // The client is loaded when it is needed: the replay player never pays for it.
    void import('@microsoft/signalr').then(async ({ HubConnectionBuilder, LogLevel }) => {
      if (stopped) return
      const conn = new HubConnectionBuilder().withUrl(pushUrl, { withCredentials: false }).withAutomaticReconnect().configureLogging(LogLevel.Error).build()
      stop = () => conn.stop()
      for (const kind of ['overlays', 'moments', 'events'] as const) {
        conn.on(kind, (m: { matchId: string; items: never[] }) => {
          if (m?.matchId === matchId) onMessage({ kind, items: m.items } as PushMessage)
        })
      }
      conn.onreconnecting(() => !stopped && setStatus('connecting'))
      conn.onreconnected(() => !stopped && setStatus('live'))
      conn.onclose(() => !stopped && setStatus('down'))
      try {
        await conn.start()
        if (!stopped) setStatus('live')
      } catch {
        if (!stopped) setStatus('down')
      }
    })
    return () => {
      stopped = true
      void stop?.()
    }
    // onMessage is stable for the lifetime of the hook that owns it
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matchId, pushUrl])

  return status
}

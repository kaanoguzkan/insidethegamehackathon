import { TopBar } from './TopBar'
import { useEffect, useState } from 'react'
import { BRAIN_URL, brainConfigured } from '../lib/brain'

interface Group { requests: number; errors: number; p50Ms: number; p95Ms: number }
interface Ops {
  uptimeS: number
  requests: { total: number; errors: number; errorRate: number; p50Ms: number | null; p95Ms: number | null; byGroup: Record<string, Group> }
  narrative: {
    stories: number; modelWritten: number; repaired: number; template: number; templateShare: number | null
    claimsVerifiedShare: number | null; cacheHitRate: number | null; modelCalls: number; hedged: number
    missedDeadline: number; rejected: number; inputTokens: number; outputTokens: number
  }
  streams: { active: number; capacity: number; retained: number; started: number; demosLoaded: string[] }
  model: { client: string; agents: string; name: string }
  cache: { enabled: boolean; connected?: boolean; entries?: number; lastError?: string | null }
  version: string
  region: string
}

const pct = (v: number | null | undefined) => (v == null ? '–' : `${Math.round(v * 100)}%`)
const ms = (v: number | null | undefined) => (v == null ? '–' : `${v} ms`)
const dur = (s: number) => (s < 3600 ? `${Math.floor(s / 60)} min` : `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`)

function Stat({ label, value, note }: { label: string; value: string | number; note?: string }) {
  return (
    <div className="ops-stat">
      <span className="ops-label">{label}</span>
      <strong>{value}</strong>
      {note && <small>{note}</small>}
    </div>
  )
}

/** What the running service is doing, read from GET /api/ops: latency and errors, how the stories were made, the live matches, the shared cache. */
export function OpsPage() {
  const [ops, setOps] = useState<Ops | null>(null)
  const [ready, setReady] = useState<{ ready: boolean; checks: Record<string, boolean> } | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (!brainConfigured) return
    let stop = false
    const load = async () => {
      try {
        const [o, r] = await Promise.all([fetch(`${BRAIN_URL}/api/ops`), fetch(`${BRAIN_URL}/ready`)])
        if (!o.ok) throw new Error(`brain: ${o.status}`)
        if (!stop) { setOps((await o.json()) as Ops); setReady((await r.json()) as { ready: boolean; checks: Record<string, boolean> }); setErr(null) }
      } catch (e) {
        if (!stop) setErr((e as Error).message)
      }
    }
    void load()
    const id = setInterval(load, 5000)
    return () => { stop = true; clearInterval(id) }
  }, [])

  const n = ops?.narrative
  return (
    <>
      <TopBar lang="en" active="ops" />
    <main className="ops">
      <header>
        <h1>Operations</h1>
        <p className="muted">The last 15 minutes of the running Brain. Read-only; nothing here identifies a viewer.</p>
      </header>
      {!brainConfigured && <p>This build has no Brain to ask.</p>}
      {err && <p role="alert">The Brain did not answer ({err}). It may be waking up.</p>}
      {ops && n && (
        <>
          <section>
            <h2>Service</h2>
            <div className="ops-grid">
              <Stat label="Ready" value={ready?.ready ? 'yes' : 'no'} note={ready ? Object.entries(ready.checks).map(([k, v]) => `${k} ${v ? '✓' : '✗'}`).join(' · ') : undefined} />
              <Stat label="Version" value={ops.version} note={ops.region || undefined} />
              <Stat label="Uptime" value={dur(ops.uptimeS)} />
              <Stat label="Model" value={ops.model.name || ops.model.client} note={`agents: ${ops.model.agents}`} />
              <Stat label="Shared cache" value={ops.cache.enabled ? (ops.cache.connected ? 'connected' : 'not connected') : 'off'} note={ops.cache.entries != null ? `${ops.cache.entries} entries` : undefined} />
              <Stat label="Live matches" value={`${ops.streams.active} / ${ops.streams.capacity}`} note={`${ops.streams.started} started since boot`} />
            </div>
          </section>
          <section>
            <h2>Requests</h2>
            <div className="ops-grid">
              <Stat label="Served" value={ops.requests.total} />
              <Stat label="Errors (5xx)" value={ops.requests.errors} note={pct(ops.requests.errorRate)} />
              <Stat label="Median" value={ms(ops.requests.p50Ms)} />
              <Stat label="95th percentile" value={ms(ops.requests.p95Ms)} />
            </div>
            <table>
              <thead><tr><th>Group</th><th>Requests</th><th>5xx</th><th>p50</th><th>p95</th></tr></thead>
              <tbody>
                {Object.entries(ops.requests.byGroup).sort().map(([g, r]) => (
                  <tr key={g}><td>{g}</td><td>{r.requests}</td><td>{r.errors}</td><td>{ms(r.p50Ms)}</td><td>{ms(r.p95Ms)}</td></tr>
                ))}
              </tbody>
            </table>
          </section>
          <section>
            <h2>The stories</h2>
            <p className="muted">How each story reached the viewer. The verifier checks every number and name against the evidence; a story that fails is repaired once, then replaced by a template.</p>
            <div className="ops-grid">
              <Stat label="Stories" value={n.stories} />
              <Stat label="Written by the model" value={n.modelWritten} />
              <Stat label="Repaired" value={n.repaired} />
              <Stat label="Template" value={n.template} note={pct(n.templateShare)} />
              <Stat label="Claims verified" value={pct(n.claimsVerifiedShare)} />
              <Stat label="Cache hits" value={pct(n.cacheHitRate)} note={`${n.modelCalls} model calls`} />
              <Stat label="Hedged calls" value={n.hedged} note={`${n.missedDeadline} missed the deadline`} />
              <Stat label="Tokens" value={`${n.inputTokens} in / ${n.outputTokens} out`} />
            </div>
          </section>
        </>
      )}
    </main>
    </>
  )
}

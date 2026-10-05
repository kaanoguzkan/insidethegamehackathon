import { useState } from 'react'
import { t } from '../../i18n'
import { clubs, colorOf, Explain, f1, PitchSvg, playerName, Segmented, surname, type ViewProps } from './common'

type Half = 'full' | 'h1' | 'h2'

export function NetworkView({ replay, a, lang }: ViewProps) {
  const [home, away] = clubs(replay)
  const [club, setClub] = useState(home.id)
  const [half, setHalf] = useState<Half>('full')
  const net = a.networks[club]?.[half]
  if (!net) return null
  const byId = new Map(net.nodes.map((n) => [n.id, n]))
  const maxEdge = Math.max(1, ...net.edges.map((e) => e.n))
  const color = colorOf(replay, club)
  const avg = net.nodes.reduce((s, n) => s + n.passes, 0) / Math.max(1, net.nodes.length)
  const strongest = net.stats.strongestLink
  return (
    <div className="ins-grid">
      <section>
        <div className="ins-controls">
          <Segmented value={club} onChange={setClub} label={t(lang, 'tab.network')} options={[{ id: home.id, label: home.short }, { id: away.id, label: away.short }]} />
          <Segmented value={half} onChange={setHalf} label={t(lang, 'net.full')} options={[{ id: 'full', label: t(lang, 'net.full') }, { id: 'h1', label: t(lang, 'net.h1') }, { id: 'h2', label: t(lang, 'net.h2') }]} />
        </div>
        <PitchSvg label={t(lang, 'tab.network')}>
          {net.edges.map((e) => {
            const p = byId.get(e.a)
            const q = byId.get(e.b)
            return p && q ? <line key={`${e.a}-${e.b}`} x1={p.x} y1={p.y} x2={q.x} y2={q.y} stroke={color} strokeOpacity={0.25 + 0.6 * (e.n / maxEdge)} strokeWidth={0.35 + 1.6 * (e.n / maxEdge)} strokeLinecap="round" /> : null
          })}
          {net.nodes.map((n) => (
            <g key={n.id}>
              <circle cx={n.x} cy={n.y} r={1.3 + Math.sqrt(n.passes) * 0.34} fill={color} stroke="#fff" strokeWidth="0.5" />
              {n.passes >= avg && <text x={n.x} y={n.y - 2.6 - Math.sqrt(n.passes) * 0.3} className="ps-text" textAnchor="middle">{surname(n.name)}</text>}
            </g>
          ))}
        </PitchSvg>
      </section>
      <section>
        <Explain>{t(lang, 'net.explain')}</Explain>
        <dl className="kv">
          <dt>{t(lang, 'net.passes')}</dt><dd>{net.stats.completedPasses}</dd>
          <dt>{t(lang, 'net.length')}</dt><dd>{f1(net.stats.avgPassLengthM)} m</dd>
          {strongest && (<><dt>{t(lang, 'net.strongest')}</dt><dd>{playerName(replay, strongest.a)} ↔ {playerName(replay, strongest.b)} ({strongest.n})</dd></>)}
        </dl>
        <table className="ins-table">
          <tbody>
            {net.nodes.slice(0, 8).map((n) => (
              <tr key={n.id}><th scope="row">{n.name}</th><td>{n.pos}</td><td className="n">{n.passes}</td></tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}

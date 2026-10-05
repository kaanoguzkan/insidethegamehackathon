import type { ReactNode } from 'react'
import type { Replay } from '../../lib/data'
import type { Analytics } from '../../lib/analytics'
import type { Lang } from '../../lib/types'

export interface ViewProps {
  replay: Replay
  a: Analytics
  lang: Lang
  ms: number
}

export const clubs = (r: Replay) => [r.meta.home, r.meta.away] as const
export const colorOf = (r: Replay, club: string) => (club === r.meta.home.id ? r.meta.home.colors.primary : r.meta.away.colors.primary)
export const shortOf = (r: Replay, club: string) => (club === r.meta.home.id ? r.meta.home.short : club === r.meta.away.id ? r.meta.away.short : club)
export const playerName = (r: Replay, pid: string | null | undefined) => {
  if (!pid) return ''
  const p = r.meta.home.players[pid] ?? r.meta.away.players[pid]
  return p?.name ?? pid
}
export const surname = (name: string | null | undefined) => (name ?? '').split(' ').slice(-1)[0]
export const f1 = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? '–' : v.toFixed(d))

/** A pitch in metres (105 x 68). ``half`` shows the attacking half (x from 52.5). Children use pitch coordinates. */
export function PitchSvg({ children, half = false, label }: { children?: ReactNode; half?: boolean; label?: string }) {
  const x0 = half ? 50 : 0
  const w = half ? 55 : 105
  return (
    <svg className="pitch-svg" viewBox={`${x0 - 2} -2 ${w + 4} 72`} role="img" aria-label={label}>
      <rect x={x0 - 2} y={-2} width={w + 4} height={72} className="ps-grass" />
      <g className="ps-lines">
        <rect x={0} y={0} width={105} height={68} />
        {!half && <line x1={52.5} x2={52.5} y1={0} y2={68} />}
        {!half && <circle cx={52.5} cy={34} r={9.15} />}
        <rect x={105 - 16.5} y={34 - 20.16} width={16.5} height={40.32} />
        <rect x={105 - 5.5} y={34 - 9.16} width={5.5} height={18.32} />
        {!half && <rect x={0} y={34 - 20.16} width={16.5} height={40.32} />}
        {!half && <rect x={0} y={34 - 9.16} width={5.5} height={18.32} />}
      </g>
      {children}
    </svg>
  )
}

export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { id: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="seg small" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.id} type="button" role="radio" aria-checked={value === o.id} className={value === o.id ? 'on' : ''} onClick={() => onChange(o.id)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Explain({ children }: { children: ReactNode }) {
  return <p className="ins-explain">{children}</p>
}

/** Two numbers side by side with proportional bars, the way a stats strip compares the teams. */
export function Versus({ label, a, b, colorA, colorB, fmt = (v: number) => String(v) }: { label: string; a: number; b: number; colorA: string; colorB: string; fmt?: (v: number) => string }) {
  const tot = a + b || 1
  return (
    <div className="versus">
      <b>{fmt(a)}</b>
      <div className="versus-mid">
        <span>{label}</span>
        <div className="versus-bar" aria-hidden="true">
          <i style={{ width: `${(a / tot) * 100}%`, background: colorA }} />
          <i style={{ width: `${(b / tot) * 100}%`, background: colorB }} />
        </div>
      </div>
      <b>{fmt(b)}</b>
    </div>
  )
}

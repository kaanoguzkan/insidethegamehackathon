import type { Meta } from './types'

/** Display clock for a match time: the second half restarts at 45:00 whatever stoppage time there was. */
export function clockAt(meta: Meta, ms: number): { period: number; minute: number; second: number; label: string } {
  const p2 = meta.periods.find((p) => p.period === 2)
  const second = p2 && ms >= p2.startMs ? 45 * 60 + (ms - p2.startMs) / 1000 : ms / 1000
  const period = p2 && ms >= p2.startMs ? 2 : 1
  const minute = Math.floor(second / 60)
  const s = Math.floor(second % 60)
  let label = `${String(minute).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  if (period === 1 && minute >= 45) label = `45+${minute - 45}:${String(s).padStart(2, '0')}`
  if (period === 2 && minute >= 90) label = `90+${minute - 90}:${String(s).padStart(2, '0')}`
  return { period, minute, second: s, label }
}

export function totalMs(meta: Meta): number {
  return Math.floor((meta.frames * 1000) / meta.hz)
}

import { winProbAt } from '../lib/analytics'
import { clockAt } from '../lib/clock'
import type { Replay } from '../lib/data'
import type { Lang } from '../lib/types'
import { t } from '../i18n'
import { Crest } from './Crest'

export function scoreAt(replay: Replay, ms: number): Record<string, number> {
  const s: Record<string, number> = { [replay.meta.home.id]: 0, [replay.meta.away.id]: 0 }
  for (const e of replay.events) {
    if (e.clock.matchMs > ms) break
    if (e.type === 'goal' && e.team) s[e.team] = (s[e.team] ?? 0) + 1
  }
  return s
}

export function Scoreboard({ replay, ms, lang }: { replay: Replay; ms: number; lang: Lang }) {
  const { home, away } = replay.meta
  const score = scoreAt(replay, ms)
  const clock = clockAt(replay.meta, ms)
  const wp = winProbAt(replay.analytics, ms)
  return (
    <header className="scoreboard" aria-label={`${home.name} ${score[home.id]}, ${away.name} ${score[away.id]}, ${clock.label}`}>
      <div className="sb-team">
        <Crest team={home} />
        <span className="sb-name">{home.short}</span>
      </div>
      <div className="sb-score">
        <b>{score[home.id]}</b>
        <span>–</span>
        <b>{score[away.id]}</b>
      </div>
      <div className="sb-team away">
        <span className="sb-name">{away.short}</span>
        <Crest team={away} />
      </div>
      <div className="sb-clock">
        <span>{clock.label}</span>
        <small>{clock.period === 1 ? t(lang, 'firstHalf') : t(lang, 'secondHalf')}</small>
      </div>
      {wp && (
        <div className="sb-wp" role="img" aria-label={`${t(lang, 'winShort')}: ${home.short} ${Math.round(wp.home * 100)}%, ${t(lang, 'wp.draw')} ${Math.round(wp.draw * 100)}%, ${away.short} ${Math.round(wp.away * 100)}%`}>
          <i style={{ width: `${wp.home * 100}%`, background: home.colors.primary }} />
          <i className="draw" style={{ width: `${wp.draw * 100}%` }} />
          <i style={{ width: `${wp.away * 100}%`, background: away.colors.primary }} />
          <span className="l">{Math.round(wp.home * 100)}%</span>
          <span className="m">{t(lang, 'winShort')}</span>
          <span className="r">{Math.round(wp.away * 100)}%</span>
        </div>
      )}
    </header>
  )
}

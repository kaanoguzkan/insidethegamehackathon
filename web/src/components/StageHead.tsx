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

/** The score, the clock and the live win probability: the one line that says where the match stands. */
export function StageHead({ replay, ms, lang }: { replay: Replay; ms: number; lang: Lang }) {
  const { home, away } = replay.meta
  const score = scoreAt(replay, ms)
  const clock = clockAt(replay.meta, ms)
  const wp = winProbAt(replay.analytics, ms)
  return (
    <header className="stage-head" aria-label={`${home.name} ${score[home.id]}, ${away.name} ${score[away.id]}, ${clock.label}`}>
      <div className="sh-team home">
        <span className="sh-name">{home.short}</span>
        <Crest team={home} size={28} />
      </div>
      <div className="sh-mid">
        <div className="sh-score" aria-hidden="true">
          <b>{score[home.id]}</b>
          <i>–</i>
          <b>{score[away.id]}</b>
        </div>
        <div className="sh-clock">
          <b>{clock.label}</b>
          <small>{clock.period === 1 ? t(lang, 'firstHalf') : t(lang, 'secondHalf')}</small>
        </div>
      </div>
      <div className="sh-team away">
        <Crest team={away} size={28} />
        <span className="sh-name">{away.short}</span>
      </div>
      {wp && (
        <div className="sh-wp" role="img" aria-label={`${t(lang, 'winShort')}: ${home.short} ${Math.round(wp.home * 100)}%, ${t(lang, 'wp.draw')} ${Math.round(wp.draw * 100)}%, ${away.short} ${Math.round(wp.away * 100)}%`}>
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

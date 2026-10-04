import { t } from '../i18n'
import type { Replay } from '../lib/data'
import type { Lang, Overlay } from '../lib/types'

interface Props {
  overlays: Overlay[]
  replay: Replay
  lang: Lang
  onWhy: (momentId: string) => void
}

const CARD_KINDS = new Set(['shot_card', 'pass_card', 'card_badge', 'stat_card'])

function latest(items: Overlay[]): Overlay | undefined {
  return items.reduce<Overlay | undefined>((a, o) => (!a || o.displayAt.matchMs > a.displayAt.matchMs ? o : a), undefined)
}

export function OverlayLayer({ overlays, replay, lang, onWhy }: Props) {
  const lower = latest(overlays.filter((o) => o.kind === 'lower_third'))
  const cards = overlays.filter((o) => CARD_KINDS.has(o.kind)).slice(-2)
  const bar = latest(overlays.filter((o) => o.kind === 'momentum_bar'))
  const meter = latest(overlays.filter((o) => o.kind === 'control_meter'))
  const tickers = overlays.filter((o) => o.kind === 'ticker').slice(-3)

  return (
    <div className="overlay-layer">
      <div className="ov-top-left">
        {bar && <MomentumBar o={bar} replay={replay} />}
        {meter && <ControlMeter o={meter} />}
      </div>
      <div className="ov-top-right">
        {tickers.map((o) => (
          <div key={o.id} className="ticker" role="status">
            <span className="ticker-dot" />
            {o.content.headline}
          </div>
        ))}
      </div>
      <div className="ov-bottom-right">
        {cards.map((o) => (
          <Card key={o.id} o={o} />
        ))}
      </div>
      <div className="ov-bottom-left">
        {lower && <LowerThird key={lower.id} o={lower} replay={replay} lang={lang} onWhy={onWhy} />}
      </div>
    </div>
  )
}

function LowerThird({ o, replay, lang, onWhy }: { o: Overlay; replay: Replay; lang: Lang; onWhy: (id: string) => void }) {
  const moment = replay.moments.find((m) => m.id === o.momentId)
  const team = moment?.subjectTeam === replay.meta.home.id ? replay.meta.home : moment?.subjectTeam === replay.meta.away.id ? replay.meta.away : null
  const level = o.provenance.fallbackLevel
  const by = level === 0 ? t(lang, 'byAgents') : level === 1 ? t(lang, 'afterRetry') : t(lang, 'byTemplate')
  return (
    <article className="lower-third" style={{ ['--accent' as string]: team?.colors.primary ?? 'var(--accent)' }} aria-label={o.content.headline}>
      <div className="lt-main">
        <h3>{o.content.headline}</h3>
        {o.content.body && <p>{o.content.body}</p>}
        {o.content.chips.length > 0 && (
          <ul className="chips">
            {o.content.chips.map((c) => (
              <li key={c.label}>
                <span>{c.label}</span>
                <b>{c.value}</b>
              </li>
            ))}
          </ul>
        )}
      </div>
      <footer>
        <span className={`prov level-${level}`} title={t(lang, `level${Math.min(level, 3)}`)}>
          <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
            <path d="M2 6.4 4.8 9 10 3.2" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {t(lang, 'verified')} · {by}
        </span>
        {o.momentId && (
          <button type="button" className="why" onClick={() => onWhy(o.momentId!)}>
            {t(lang, 'why')}
          </button>
        )}
      </footer>
    </article>
  )
}

function Card({ o }: { o: Overlay }) {
  return (
    <article className={`card kind-${o.kind}`} aria-label={o.content.headline}>
      <h4>{o.content.headline}</h4>
      {o.content.body && <p>{o.content.body}</p>}
      {o.content.chips.length > 0 && (
        <ul className="chips">
          {o.content.chips.map((c) => (
            <li key={c.label}>
              <span>{c.label}</span>
              <b>{c.value}</b>
            </li>
          ))}
        </ul>
      )}
    </article>
  )
}

function MomentumBar({ o, replay }: { o: Overlay; replay: Replay }) {
  const [a, b] = o.content.chips
  const pa = parseFloat(a?.value ?? '50')
  return (
    <div className="meter" role="img" aria-label={`${o.content.headline}: ${a?.label} ${a?.value}, ${b?.label} ${b?.value}`}>
      <div className="meter-head">{o.content.headline}</div>
      <div className="meter-bar">
        <i style={{ width: `${pa}%`, background: replay.meta.home.colors.primary }} />
        <i style={{ width: `${100 - pa}%`, background: replay.meta.away.colors.primary }} />
      </div>
      <div className="meter-foot">
        <span>{a?.label} {a?.value}</span>
        <span>{b?.label} {b?.value}</span>
      </div>
    </div>
  )
}

function ControlMeter({ o }: { o: Overlay }) {
  const c = o.content.chips[0]
  return (
    <div className="meter slim">
      <div className="meter-head">
        {o.content.headline}: <b>{c?.label}</b> · {c?.value}
      </div>
    </div>
  )
}

import { t } from '../i18n'
import type { Replay } from '../lib/data'
import type { Lang, Profile } from '../lib/types'
import type { Step } from '../hooks/useHash'
import { MomentList } from './MomentList'
import { RecapPanel } from './RecapPanel'
import { TacticsPanel } from './TacticsPanel'

export type RailTab = 'story' | 'tactics' | 'moments'
const TABS: RailTab[] = ['story', 'tactics', 'moments']

interface Props {
  step: Step
  tab: RailTab
  onTab: (t: RailTab) => void
  onStep: (s: Step) => void
  replay: Replay
  profile: Profile
  ms: number
  selected: string | null
  onPick: (id: string) => void
}

/**
 * The right-hand column. Watching shows only the moments to jump to; understanding adds the story and the tactics.
 * Each ends with the way to go one level deeper.
 */
export function Rail({ step, tab, onTab, onStep, replay, profile, ms, selected, onPick }: Props) {
  const lang: Lang = profile.language
  const understand = step === 'understand'
  const active: RailTab = understand ? tab : 'moments'
  return (
    <aside className="rail" aria-label={t(lang, `step.${step}`)}>
      {understand ? (
        <div className="rail-tabs" role="tablist" aria-label={t(lang, 'step.understand')}>
          {TABS.map((id) => (
            <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? 'on' : ''} onClick={() => onTab(id)}>
              {t(lang, `rail.${id}`)}
            </button>
          ))}
        </div>
      ) : (
        <div className="rail-head">
          <h2>{t(lang, 'moments')}</h2>
        </div>
      )}
      <div className="rail-body" role={understand ? 'tabpanel' : undefined}>
        {active === 'story' && <RecapPanel replay={replay} profile={profile} ms={ms} onPick={onPick} />}
        {active === 'tactics' && <TacticsPanel replay={replay} ms={ms} lang={lang} />}
        {active === 'moments' && (
          <>
            <p className="hint">{t(lang, 'momentsHint')}</p>
            <MomentList replay={replay} lang={lang} selected={selected} onPick={onPick} />
          </>
        )}
      </div>
      {step !== 'explore' && (
        <footer className="rail-next">
          <button type="button" className="btn wide" onClick={() => onStep(understand ? 'explore' : 'understand')}>
            {t(lang, understand ? 'next.explore' : 'next.understand')}
          </button>
        </footer>
      )}
    </aside>
  )
}

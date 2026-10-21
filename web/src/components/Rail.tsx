import { t } from '../i18n'
import type { Replay } from '../lib/data'
import type { Layers } from '../lib/layers'
import type { Lang, Profile } from '../lib/types'
import { AskPanel } from './AskPanel'
import { Insights, type ViewId } from './insights/Insights'
import { MomentList } from './MomentList'
import { RecapPanel } from './RecapPanel'
import { TacticsPanel } from './TacticsPanel'

/** The right-hand panel: one tab bar that is always there, so any view of the match is one click away and the pitch never leaves the screen. */
export type PanelTab = 'moments' | 'story' | 'tactics' | 'numbers' | 'ask'
export const PANEL_TABS: PanelTab[] = ['moments', 'story', 'tactics', 'numbers', 'ask']
const LIVE_TABS: PanelTab[] = ['moments', 'story', 'tactics', 'numbers'] // Ask answers from a finished match: not offered while one is being played

interface Props {
  tab: PanelTab
  onTab: (t: PanelTab) => void
  replay: Replay
  profile: Profile
  ms: number
  selected: string | null
  onPick: (id: string) => void
  live?: boolean
  // the Numbers workspace
  numbersTab: ViewId
  onNumbersTab: (id: ViewId) => void
  layers: Layers
  onLens: (keys: (keyof Layers)[], on: boolean) => void
}

export function Rail({ tab, onTab, replay, profile, ms, selected, onPick, live = false, numbersTab, onNumbersTab, layers, onLens }: Props) {
  const lang: Lang = profile.language
  const tabs = live ? LIVE_TABS : PANEL_TABS
  return (
    <aside className="rail" aria-label={t(lang, `rail.${tab}`)}>
      <div className="rail-tabs" role="tablist" aria-label={t(lang, 'path')}>
        {tabs.map((id, i) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? 'on' : ''} onClick={() => onTab(id)} title={`${t(lang, `rail.${id}.d`)} (${i + 1})`}>
            {t(lang, `rail.${id}`)}
          </button>
        ))}
      </div>
      <div className={`rail-body${tab === 'numbers' ? ' flush' : ''}`} role="tabpanel">
        {tab === 'moments' && (
          <>
            <p className="hint">{t(lang, 'momentsHint')}</p>
            <MomentList replay={replay} lang={lang} selected={selected} onPick={onPick} />
          </>
        )}
        {tab === 'story' && <RecapPanel replay={replay} profile={profile} ms={ms} onPick={onPick} />}
        {tab === 'tactics' && <TacticsPanel replay={replay} ms={ms} lang={lang} />}
        {tab === 'ask' && <AskPanel replay={replay} profile={profile} ms={ms} />}
        {tab === 'numbers' &&
          (replay.analytics ? (
            <Insights replay={replay} ms={ms} lang={lang} tab={numbersTab} onTab={onNumbersTab} layers={layers} onLens={onLens} />
          ) : (
            <p className="muted pad">{t(lang, live ? 'stream.analytics' : 'noAnalytics')}</p>
          ))}
      </div>
    </aside>
  )
}

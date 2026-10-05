import { useState } from 'react'
import { t } from '../../i18n'
import type { Replay } from '../../lib/data'
import type { Lang } from '../../lib/types'
import { DeadBallView } from './DeadBallView'
import { NetworkView } from './NetworkView'
import { PhysicalView } from './PhysicalView'
import { PlayersView } from './PlayersView'
import { SeasonView } from './SeasonView'
import { ShapeView } from './ShapeView'
import { ShotsView } from './Shots'
import { SpaceView } from './SpaceView'
import { TransitionsView } from './TransitionsView'
import { ValueView } from './ValueView'
import { WinProbView } from './WinProb'

const TABS = [
  ['win', WinProbView], ['shots', ShotsView], ['value', ValueView], ['network', NetworkView], ['shape', ShapeView],
  ['space', SpaceView], ['players', PlayersView], ['dead', DeadBallView], ['trans', TransitionsView], ['physical', PhysicalView], ['season', SeasonView],
] as const

type Id = (typeof TABS)[number][0]

/** The match-analytics panel: one tab per Opta-style view, rendered only when selected. */
export function Insights({ replay, ms, lang }: { replay: Replay; ms: number; lang: Lang }) {
  const [tab, setTab] = useState<Id>('win')
  const a = replay.analytics
  if (!a) {
    return (
      <section className="panel insights">
        <h2 className="panel-title">{t(lang, 'insights')}</h2>
        <p className="muted">{t(lang, 'noAnalytics')}</p>
      </section>
    )
  }
  const View = TABS.find(([id]) => id === tab)![1]
  return (
    <section className="panel insights">
      <h2 className="panel-title">{t(lang, 'insights')}</h2>
      <div className="ins-tabs" role="tablist" aria-label={t(lang, 'insights')}>
        {TABS.map(([id]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? 'on' : ''} onClick={() => setTab(id)}>
            {t(lang, `tab.${id}`)}
          </button>
        ))}
      </div>
      <div className="ins-body" role="tabpanel">
        <View replay={replay} a={a} lang={lang} ms={ms} />
      </div>
    </section>
  )
}

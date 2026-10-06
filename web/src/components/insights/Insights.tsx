import { t } from '../../i18n'
import type { Replay } from '../../lib/data'
import type { Layers } from '../../lib/layers'
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

const VIEWS = {
  win: WinProbView, shots: ShotsView, value: ValueView, network: NetworkView, shape: ShapeView,
  space: SpaceView, players: PlayersView, dead: DeadBallView, trans: TransitionsView, physical: PhysicalView, season: SeasonView,
}
export type ViewId = keyof typeof VIEWS

/** The Explore menu: each group answers one question, each view is one way of answering it. */
export const GROUPS: { id: string; views: ViewId[] }[] = [
  { id: 'match', views: ['win', 'shots', 'value'] },
  { id: 'space', views: ['shape', 'space', 'network'] },
  { id: 'people', views: ['players', 'physical'] },
  { id: 'phases', views: ['dead', 'trans'] },
  { id: 'context', views: ['season'] },
]

/** Views that have a live drawing on the pitch: the lens to switch on to see the same thing there. */
const LENS_FOR: Partial<Record<ViewId, (keyof Layers)[]>> = { space: ['control'], shape: ['shape'], physical: ['runs'] }

interface Props {
  replay: Replay
  ms: number
  lang: Lang
  tab: ViewId
  onTab: (id: ViewId) => void
  layers: Layers
  onLens: (keys: (keyof Layers)[], on: boolean) => void
}

export const isViewId = (v: string | null): v is ViewId => !!v && v in VIEWS

export function Insights({ replay, ms, lang, tab, onTab, layers, onLens }: Props) {
  const a = replay.analytics
  if (!a) {
    return (
      <section className="explore">
        <p className="muted">{t(lang, 'noAnalytics')}</p>
      </section>
    )
  }
  const View = VIEWS[tab]
  const lens = LENS_FOR[tab]
  const lensOn = !!lens && lens.every((k) => layers[k])
  return (
    <section className="explore" aria-label={t(lang, 'insights')}>
      <nav className="ex-nav" aria-label={t(lang, 'exploreNav')}>
        {GROUPS.map((g) => (
          <div key={g.id} className="ex-group">
            <h3>{t(lang, `group.${g.id}`)}</h3>
            {g.views.map((id) => (
              <button key={id} type="button" aria-current={tab === id ? 'page' : undefined} className={tab === id ? 'on' : ''} onClick={() => onTab(id)}>
                {t(lang, `tab.${id}`)}
              </button>
            ))}
          </div>
        ))}
      </nav>
      <div className="ex-body" key={tab}>
        {lens && (
          <div className="ex-tools">
            <button type="button" className={`btn${lensOn ? ' on' : ''}`} aria-pressed={lensOn} onClick={() => onLens(lens, !lensOn)}>
              {t(lang, 'showOnPitch')}
            </button>
          </div>
        )}
        <View replay={replay} a={a} lang={lang} ms={ms} />
      </div>
    </section>
  )
}

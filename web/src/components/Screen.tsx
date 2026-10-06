import { lazy, Suspense, useMemo, useState, type MutableRefObject } from 'react'
import { cohortOf } from '../lib/cohort'
import type { Replay } from '../lib/data'
import { NO_LAYERS, type Layers } from '../lib/layers'
import { visibleOverlays } from '../lib/overlays'
import { t } from '../i18n'
import type { Overlay, Profile } from '../lib/types'
import { OverlayLayer } from './OverlayLayer'
import { webglSupported, type Cam } from '../lib/webgl'
import { Pitch, type PitchBadge } from './Pitch'

const Pitch3D = lazy(() => import('./Pitch3D'))
const CAN_3D = typeof document !== 'undefined' && webglSupported()

interface Props {
  replay: Replay
  ms: number
  msRef: MutableRefObject<number>
  profile: Profile
  evidenceMoment: string | null
  onWhy: (momentId: string) => void
  title?: string
  overlays?: Overlay[] // defaults to the package's own (healthy) overlays
  overlayOnly?: boolean // the broadcast page: graphics only, transparent background
  layers?: Layers // live pitch graphics (pitch control, shape, offside line ...)
  cam?: Cam // '2d' or a 3D camera preset
  follow?: boolean // the 3D camera follows the ball
}

/** One viewer's view of the match: scoreboard, pitch and the overlays written for their cohort. */
export function Screen({ replay, ms, msRef, profile, evidenceMoment, onWhy, title, overlayOnly, overlays, layers = NO_LAYERS, cam = '2d', follow = false }: Props) {
  const [failed3d, setFailed3d] = useState(false)
  const viewer = cohortOf(profile)
  const visible = useMemo(() => visibleOverlays(overlays ?? replay.overlays, ms, profile, viewer), [replay, overlays, ms, profile, viewer.mode, viewer.language, viewer.perspective, viewer.focusPlayer]) // eslint-disable-line react-hooks/exhaustive-deps
  const badges: PitchBadge[] = visible
    .filter((o) => o.anchor.type === 'player' && o.anchor.player && o.content.chips[0])
    .map((o) => ({ playerId: o.anchor.player!, text: o.content.chips[0].value }))
  const evidence = useMemo(() => {
    const m = replay.moments.find((x) => x.id === evidenceMoment)
    if (!m) return null
    return m.eventIds.map((id) => replay.eventsById.get(id)).filter((e): e is NonNullable<typeof e> => !!e && !!e.location)
  }, [replay, evidenceMoment])
  const lowerNow = visible.filter((o) => o.kind === 'lower_third').slice(-1)[0]
  const graphics = useMemo(() => visible.filter((o) => o.kind === 'pitch_graphic'), [visible])
  const lang = profile.language
  const labels = useMemo(() => ({ offside: t(lang, 'layer.offside'), runs: { in_behind: t(lang, 'run.in_behind'), overlap: t(lang, 'run.overlap'), drop: t(lang, 'run.drop') } }), [lang])

  if (overlayOnly) {
    return (
      <section className={`screen bare${profile.highContrast ? ' hc' : ''}${profile.reducedMotion ? ' calm' : ''}`} aria-label={title}>
        <OverlayLayer overlays={visible} replay={replay} lang={profile.language} onWhy={onWhy} />
        {profile.audioDescribed && (
          <div className="sr-only" aria-live="polite" aria-atomic="true">
            {lowerNow ? `${lowerNow.content.headline}. ${lowerNow.content.body}` : ''}
          </div>
        )}
      </section>
    )
  }

  return (
    <section className={`screen${profile.highContrast ? ' hc' : ''}${profile.reducedMotion ? ' calm' : ''}`} aria-label={title}>
      {title && <div className="screen-title">{title}</div>}
      <div className="stage">
        {(() => {
          const flat = (
            <Pitch
              replay={replay}
              msRef={msRef}
              focusPlayer={profile.focusPlayer}
              evidence={evidence}
              badges={badges}
              layers={layers}
              graphics={graphics}
              labels={labels}
              highContrast={profile.highContrast}
              reducedMotion={profile.reducedMotion}
              label={`${replay.meta.home.name} v ${replay.meta.away.name}`}
            />
          )
          if (cam === '2d' || !CAN_3D || failed3d) return flat
          return (
            <Suspense fallback={flat}>
              <Pitch3D
                replay={replay}
                msRef={msRef}
                focusPlayer={profile.focusPlayer}
                evidence={evidence}
                badges={badges}
                layers={layers}
                graphics={graphics}
                labels={labels}
                highContrast={profile.highContrast}
                reducedMotion={profile.reducedMotion}
                label={`${replay.meta.home.name} v ${replay.meta.away.name}`}
                cam={cam}
                follow={follow}
                onFail={() => setFailed3d(true)}
              />
            </Suspense>
          )
        })()}
        <OverlayLayer overlays={visible} replay={replay} lang={profile.language} onWhy={onWhy} />
      </div>
      {profile.audioDescribed && (
        <div className="sr-only" aria-live="polite" aria-atomic="true">
          {lowerNow ? `${lowerNow.content.headline}. ${lowerNow.content.body}` : ''}
        </div>
      )}
    </section>
  )
}

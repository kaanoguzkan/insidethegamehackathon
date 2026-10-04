import { useMemo, type MutableRefObject } from 'react'
import { cohortOf } from '../lib/cohort'
import type { Replay } from '../lib/data'
import { visibleOverlays } from '../lib/overlays'
import type { Overlay, Profile } from '../lib/types'
import { OverlayLayer } from './OverlayLayer'
import { Pitch, type PitchBadge } from './Pitch'
import { Scoreboard } from './Scoreboard'

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
}

/** One viewer's view of the match: scoreboard, pitch and the overlays written for their cohort. */
export function Screen({ replay, ms, msRef, profile, evidenceMoment, onWhy, title, overlayOnly, overlays }: Props) {
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
      <Scoreboard replay={replay} ms={ms} lang={profile.language} />
      <div className="stage">
        <Pitch
          replay={replay}
          msRef={msRef}
          focusPlayer={profile.focusPlayer}
          evidence={evidence}
          badges={badges}
          highContrast={profile.highContrast}
          reducedMotion={profile.reducedMotion}
          label={`${replay.meta.home.name} v ${replay.meta.away.name}`}
        />
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

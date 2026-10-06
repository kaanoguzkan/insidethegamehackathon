import { t } from '../i18n'
import type { Phase } from '../lib/analytics'
import type { Lang } from '../lib/types'

/** The phase a team is in right now, with the shape it plays in that phase. */
export function PhaseChip({ phase, shape, lang }: { phase: Phase | null; shape?: string | null; lang: Lang }) {
  if (!phase) return null
  return (
    <span className={`phase-chip ph-${phase}`} title={t(lang, `phase.${phase}.d`)}>
      <i aria-hidden="true" />
      {t(lang, `phase.${phase}`)}
      {shape && <small>{shape}</small>}
    </span>
  )
}

/** The designed shape for a phase from a team's shape labels (a low block is the block, squeezed). */
export function shapeFor(phase: Phase, s: { attack: string | null; block: string | null; build: string | null; press: string | null } | null | undefined): string | null {
  if (!s) return null
  return phase === 'attack' ? s.attack : phase === 'build' ? s.build : phase === 'press' ? s.press : s.block
}

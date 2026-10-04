import type { TeamMeta } from '../lib/types'

/** A generated shield monogram. Clubs are fictional, so the crests are too. */
export function Crest({ team, size = 28 }: { team: TeamMeta; size?: number }) {
  const { primary, secondary } = team.colors
  const id = `crest-${team.id}`
  return (
    <svg width={size} height={size} viewBox="0 0 32 36" role="img" aria-label={`${team.name} crest`}>
      <defs>
        <clipPath id={id}>
          <path d="M16 1.5 29.5 5v13.2c0 8-5.6 13.4-13.5 16.3C8.1 31.6 2.5 26.2 2.5 18.2V5z" />
        </clipPath>
      </defs>
      <g clipPath={`url(#${id})`}>
        <rect width="32" height="36" fill={primary} />
        <rect y="22" width="32" height="14" fill={secondary} opacity="0.92" />
        <rect x="14" width="4" height="36" fill={secondary} opacity="0.25" />
      </g>
      <path d="M16 1.5 29.5 5v13.2c0 8-5.6 13.4-13.5 16.3C8.1 31.6 2.5 26.2 2.5 18.2V5z" fill="none" stroke="rgba(255,255,255,.55)" strokeWidth="1.2" />
      <text x="16" y="17" textAnchor="middle" fontSize="9.5" fontWeight="800" fill={secondary} stroke={primary} strokeWidth="0.6" paintOrder="stroke" fontFamily="system-ui, sans-serif">
        {team.id}
      </text>
    </svg>
  )
}

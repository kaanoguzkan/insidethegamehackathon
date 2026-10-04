import { momentTypeLabel, t } from '../i18n'
import type { Replay } from '../lib/data'
import type { Lang } from '../lib/types'

interface Props {
  replay: Replay
  lang: Lang
  selected: string | null
  onPick: (momentId: string) => void
}

export function MomentList({ replay, lang, selected, onPick }: Props) {
  const items = [...replay.moments].filter((m) => m.salience >= 0.4).sort((a, b) => a.detectedAt.matchMs - b.detectedAt.matchMs)
  const name = (id: string | null) => (id === replay.meta.home.id ? replay.meta.home.short : id === replay.meta.away.id ? replay.meta.away.short : '')
  return (
    <ol className="moments" aria-label={t(lang, 'moments')}>
      {items.map((m) => (
        <li key={m.id}>
          <button type="button" className={m.id === selected ? 'on' : ''} onClick={() => onPick(m.id)}>
            <span className={`dot type-${m.type}`} aria-hidden="true" />
            <span className="m-time">{m.detectedAt.label}</span>
            <span className="m-type">{momentTypeLabel(lang, m.type)}</span>
            <span className="m-team">{name(m.subjectTeam)}</span>
            <span className="m-sal" title={`salience ${m.salience}`} aria-hidden="true"><i style={{ width: `${Math.round(m.salience * 100)}%` }} /></span>
            {m.level === 2 && <span className="m-tpl" title={t(lang, 'level2')}>T</span>}
          </button>
        </li>
      ))}
    </ol>
  )
}

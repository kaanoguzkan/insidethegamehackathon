import { useState } from 'react'
import { t } from '../i18n'
import { totalMs } from '../lib/clock'
import type { Replay } from '../lib/data'
import { RECAP_KINDS, recapFor, recapReady } from '../lib/recap'
import type { Profile, Recap } from '../lib/types'

interface Props {
  replay: Replay
  profile: Profile
  ms: number
  onPick: (momentId: string) => void
}

const LABEL: Record<Recap['kind'], string> = { preview: 'recapPreview', half_time: 'recapHalf', full_time: 'recapFull' }

export function RecapPanel({ replay, profile, ms, onPick }: Props) {
  const lang = profile.language
  const half = replay.meta.periods.find((p) => p.period === 1)?.endMs ?? 45 * 60_000
  const end = totalMs(replay.meta)
  const [kind, setKind] = useState<Recap['kind']>('preview')
  if (replay.recaps.length === 0) return null
  const ready = recapReady(kind, ms, half, end - 1000)
  const recap = recapFor(replay.recaps, kind, profile)
  return (
    <section className="panel recap" aria-label={t(lang, 'recaps')}>
      <h2 className="panel-title">{t(lang, 'recaps')}</h2>
      <div className="seg" role="tablist" aria-label={t(lang, 'recaps')}>
        {RECAP_KINDS.map((k) => (
          <button key={k} type="button" role="tab" aria-selected={kind === k} className={kind === k ? 'on' : ''} onClick={() => setKind(k)}>
            {t(lang, LABEL[k])}
          </button>
        ))}
      </div>
      {!ready || !recap ? (
        <p className="muted recap-wait">{t(lang, 'recapWait')}</p>
      ) : (
        <article>
          <h3>{recap.headline}</h3>
          <p>{recap.summary}</p>
          {recap.stats.length > 0 && (
            <ul className="chips">
              {recap.stats.map((c) => (
                <li key={c.label}><span>{c.label}</span><b>{c.value}</b></li>
              ))}
            </ul>
          )}
          {recap.key_moments.length > 0 && (
            <ol className="recap-moments">
              {recap.key_moments.map((m) => (
                <li key={m.momentId}>
                  <button type="button" onClick={() => onPick(m.momentId)}><b>{m.label}</b> {m.text}</button>
                </li>
              ))}
            </ol>
          )}
          <p className="prov level-0">✓ {t(lang, 'verified')} · {recap.provenance.fallbackLevel === 0 ? t(lang, 'byAgents') : t(lang, 'byTemplate')}</p>
        </article>
      )}
    </section>
  )
}

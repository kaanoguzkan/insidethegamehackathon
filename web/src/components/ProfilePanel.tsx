import { t } from '../i18n'
import type { Replay } from '../lib/data'
import type { Lang, Profile } from '../lib/types'

const LANGS: { id: Lang; label: string }[] = [
  { id: 'en', label: 'English' },
  { id: 'es', label: 'Español' },
  { id: 'tr', label: 'Türkçe' },
]

interface Props {
  profile: Profile
  onChange: (p: Profile) => void
  replay: Replay
  heading?: string
}

function Seg<T extends string>({ value, options, onChange, label }: { value: T; options: { id: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="seg" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.id} type="button" role="radio" aria-checked={value === o.id} className={value === o.id ? 'on' : ''} onClick={() => onChange(o.id)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function ProfilePanel({ profile, onChange, replay, heading }: Props) {
  const lang = profile.language
  const set = (patch: Partial<Profile>) => onChange({ ...profile, ...patch })
  const players = [replay.meta.home, replay.meta.away].flatMap((team) =>
    team.lineup.map((id) => ({ id, team: team.short, ...team.players[id] })),
  )
  return (
    <fieldset className="panel profile">
      <legend>{heading ?? t(lang, 'viewer')}</legend>
      <Seg
        label={t(lang, 'viewer')}
        value={profile.mode}
        onChange={(mode) => set({ mode })}
        options={[
          { id: 'analyst', label: t(lang, 'analyst') },
          { id: 'casual', label: t(lang, 'casual') },
        ]}
      />
      <Seg label={t(lang, 'language')} value={lang} onChange={(language) => set({ language })} options={LANGS} />
      <label className="field">
        <span>{t(lang, 'club')}</span>
        <select value={profile.perspective} onChange={(e) => set({ perspective: e.target.value })} disabled={profile.mode === 'analyst'}>
          <option value="neutral">{t(lang, 'neutral')}</option>
          <option value={replay.meta.home.id}>{replay.meta.home.name}</option>
          <option value={replay.meta.away.id}>{replay.meta.away.name}</option>
        </select>
      </label>
      <label className="field">
        <span>{t(lang, 'follow')}</span>
        <select value={profile.focusPlayer ?? ''} onChange={(e) => set({ focusPlayer: e.target.value || null })}>
          <option value="">{t(lang, 'nobody')}</option>
          {players.map((p) => (
            <option key={p.id} value={p.id}>
              {p.team} · {p.number} {p.name}
            </option>
          ))}
        </select>
      </label>
      <Seg
        label={t(lang, 'density')}
        value={profile.density}
        onChange={(density) => set({ density })}
        options={[
          { id: 'low', label: t(lang, 'low') },
          { id: 'medium', label: t(lang, 'medium') },
          { id: 'high', label: t(lang, 'high') },
        ]}
      />
      <div className="checks">
        <label><input type="checkbox" checked={profile.audioDescribed} onChange={(e) => set({ audioDescribed: e.target.checked })} /> {t(lang, 'audioDescribed')}</label>
        <label><input type="checkbox" checked={profile.reducedMotion} onChange={(e) => set({ reducedMotion: e.target.checked })} /> {t(lang, 'reducedMotion')}</label>
        <label><input type="checkbox" checked={profile.highContrast} onChange={(e) => set({ highContrast: e.target.checked })} /> {t(lang, 'highContrast')}</label>
      </div>
    </fieldset>
  )
}

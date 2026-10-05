import { t } from '../i18n'
import { LAYER_KEYS, type Layers } from '../lib/layers'
import type { Lang } from '../lib/types'

/** Toggles for the live pitch graphics: each is drawn from the tracking frame under the players. */
export function GraphicsBar({ layers, onToggle, onClear, lang }: { layers: Layers; onToggle: (k: (typeof LAYER_KEYS)[number]) => void; onClear: () => void; lang: Lang }) {
  const any = LAYER_KEYS.some((k) => layers[k])
  return (
    <div className="graphics-bar" role="group" aria-label={t(lang, 'graphics')}>
      <span>{t(lang, 'graphics')}</span>
      {LAYER_KEYS.map((k) => (
        <button key={k} type="button" className={`chip-btn${layers[k] ? ' on' : ''}`} aria-pressed={layers[k]} onClick={() => onToggle(k)}>
          {t(lang, `layer.${k}`)}
        </button>
      ))}
      {any && (
        <button type="button" className="chip-btn clear" onClick={onClear} aria-label={t(lang, 'close')}>×</button>
      )}
    </div>
  )
}

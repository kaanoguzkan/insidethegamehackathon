import { useEffect, useRef, useState } from 'react'
import { t } from '../i18n'
import { type AskAnswer, askBrain, BRAIN_URL, brainConfigured, prewarm, waitWarm, wakeBrain } from '../lib/brain'
import type { Replay } from '../lib/data'
import type { Profile } from '../lib/types'

interface Props {
  replay: Replay
  profile: Profile
  ms: number
}

type Turn = { id: number; question: string; answer?: AskAnswer; error?: 'failed' | 'rate' }

export const formatCost = (usd: number): string => (usd === 0 ? '$0' : usd < 0.01 ? `<$0.01 (≈$${usd.toFixed(4)})` : `$${usd.toFixed(2)}`)

/**
 * "Ask the match": a question box. The Brain answers from the match-data tools only and checks every number, so each
 * answer says which tools it looked at, whether it was checked, how long it took and what it cost.
 */
export function AskPanel({ replay, profile, ms }: Props) {
  const lang = profile.language
  const [turns, setTurns] = useState<Turn[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState<'waking' | 'loading' | 'asking' | null>(null)
  const awake = useRef(false)
  const end = useRef<HTMLDivElement>(null)
  const next = useRef(1)

  useEffect(() => {
    setTurns([])
    awake.current = false
    if (brainConfigured) prewarm(BRAIN_URL, replay.id) // opening the tab starts the Brain (if asleep) and loads this match's data while the viewer types
  }, [replay.id])
  useEffect(() => end.current?.scrollIntoView?.({ block: 'nearest' }), [turns, busy])

  if (!brainConfigured) return <p className="hint">{t(lang, 'askNeedsBrain')}</p>

  const send = async (question: string) => {
    const q = question.trim()
    if (q.length < 2 || busy) return
    const id = next.current++
    setText('')
    setTurns((v) => [...v, { id, question: q }])
    try {
      if (!awake.current) {
        setBusy('waking')
        awake.current = await wakeBrain(BRAIN_URL)
        setBusy('loading')
        await waitWarm(replay.id, BRAIN_URL)
      }
      setBusy('asking')
      const answer = await askBrain({ matchId: replay.id, question: q, language: lang, mode: profile.mode, minute: Math.round(ms / 60000) })
      setTurns((v) => v.map((x) => (x.id === id ? { ...x, answer } : x)))
    } catch (e) {
      setTurns((v) => v.map((x) => (x.id === id ? { ...x, error: (e as Error).message === 'rate' ? 'rate' : 'failed' } : x)))
    } finally {
      setBusy(null)
    }
  }

  const suggestions = [t(lang, 'askSuggest1'), t(lang, 'askSuggest2'), t(lang, 'askSuggest3')]
  return (
    <div className="ask">
      <p className="hint">{t(lang, 'askHint')}</p>
      <div className="ask-log" role="log" aria-live="polite" aria-label={t(lang, 'askTitle')}>
        {turns.length === 0 && (
          <div className="ask-suggest">
            {suggestions.map((s) => (
              <button key={s} type="button" className="btn" disabled={!!busy} onClick={() => void send(s)}>{s}</button>
            ))}
          </div>
        )}
        {turns.map((turn) => (
          <div key={turn.id} className="ask-turn">
            <p className="ask-q">{turn.question}</p>
            {turn.answer && (
              <div className="ask-a">
                <p>{turn.answer.answer}</p>
                <p className="ask-meta">
                  {turn.answer.level === 2 && <span className="ask-note">{t(lang, 'askFromFacts')}</span>}
                  {turn.answer.level === 1 && <span className="ask-note">{t(lang, 'askMended')}</span>}
                  {turn.answer.level <= 1 && !turn.answer.refused && <span className="ask-ok">✓ {t(lang, 'askVerified')}</span>}
                  {turn.answer.tools.length > 0 && <span>{t(lang, 'askUsed')}: {turn.answer.tools.map((x) => x.name.replace(/^get_/, '')).join(', ')}</span>}
                  <span>{(turn.answer.elapsedMs / 1000).toFixed(1)}{t(lang, 'liveSeconds')} · {formatCost(turn.answer.usage.costUsd)}</span>
                </p>
              </div>
            )}
            {turn.error && <p className="ask-a caveat">{t(lang, turn.error === 'rate' ? 'askRate' : 'askError')}</p>}
          </div>
        ))}
        {busy && <p role="status" className="hint">{t(lang, busy === 'waking' ? 'askWaking' : busy === 'loading' ? 'askLoading' : 'askThinking')}</p>}
        <div ref={end} />
      </div>
      <form className="ask-form" onSubmit={(e) => { e.preventDefault(); void send(text) }}>
        <label className="sr-only" htmlFor="ask-input">{t(lang, 'askLabel')}</label>
        <input id="ask-input" value={text} maxLength={280} placeholder={t(lang, 'askPlaceholder')} onChange={(e) => setText(e.target.value)} disabled={!!busy} autoComplete="off" />
        <button type="submit" className="btn on" disabled={!!busy || text.trim().length < 2}>{t(lang, 'askSend')}</button>
        {turns.length > 0 && <button type="button" className="btn" disabled={!!busy} onClick={() => setTurns([])}>{t(lang, 'askClear')}</button>}
      </form>
    </div>
  )
}

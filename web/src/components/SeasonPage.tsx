import { useEffect, useState } from 'react'
import { t } from '../i18n'
import { BRAIN_URL, brainConfigured, wakeBrain } from '../lib/brain'
import { fixtureLabel, getSeason, SeasonBusy, type SeasonView, simulateSeason, tune } from '../lib/season'
import type { Profile } from '../lib/types'
import { SeasonTable } from './SeasonTable'

interface Props {
  profile: Profile
  onProfile: (p: Partial<Profile>) => void
}

/** The season: simulation progress, the table and every fixture with its result. Any simulated fixture can be put on air. */
export function SeasonPage({ profile, onProfile }: Props) {
  const lang = profile.language
  const [view, setView] = useState<SeasonView | null>(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    if (!brainConfigured) return
    const ctl = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = async () => {
      let again = 3000
      try {
        const v = await getSeason(BRAIN_URL, AbortSignal.any([ctl.signal, AbortSignal.timeout(60_000)]))
        setView(v)
        if (v.seasonId && v.done >= v.total) again = 15_000 // finished: only watch for a new season
      } catch {
        /* the Brain may still be waking */
      }
      if (!ctl.signal.aborted) timer = setTimeout(load, again)
    }
    void wakeBrain(BRAIN_URL, ctl.signal).then(() => !ctl.signal.aborted && void load())
    return () => {
      ctl.abort()
      if (timer) clearTimeout(timer)
    }
  }, [reload])

  const simulate = async () => {
    setBusy(true)
    setNote(null)
    try {
      await simulateSeason()
      setReload((n) => n + 1)
    } catch (e) {
      if (e instanceof SeasonBusy) {
        setNote(t(lang, 'season.busy'))
        setReload((n) => n + 1)
      } else setNote(t(lang, 'season.failed'))
    } finally {
      setBusy(false)
    }
  }

  const watch = async (fixtureId: string) => {
    try {
      await tune({ fixtureId })
    } catch {
      /* the home page tunes in again and shows what is wrong */
    }
    window.location.hash = '#/'
  }

  if (!brainConfigured) {
    return (
      <main className="live-page">
        <header className="live-head"><a className="btn" href="#/">{t(lang, 'season.back')}</a><h1>{t(lang, 'season.title')}</h1><p className="caveat">{t(lang, 'live.nobrain')}</p></header>
      </main>
    )
  }

  const rounds = new Map<number, SeasonView['fixtures']>()
  for (const f of view?.fixtures ?? []) rounds.set(f.round, [...(rounds.get(f.round) ?? []), f])
  const simulating = !!view?.seasonId && view.done < view.total
  const pct = view && view.total ? Math.round((100 * view.done) / view.total) : 0

  return (
    <main className="live-page season">
      <header className="live-head">
        <nav className="live-nav">
          <a className="btn" href="#/">{t(lang, 'season.back')}</a>
          <a className="btn" href="#/replay">{t(lang, 'season.replays')}</a>
          <span className="live-lang">
            {(['en', 'es', 'tr'] as const).map((l) => <button key={l} type="button" className={`chip${l === lang ? ' on' : ''}`} aria-pressed={l === lang} onClick={() => onProfile({ language: l })}>{l.toUpperCase()}</button>)}
          </span>
        </nav>
        <h1>{t(lang, 'season.title')}</h1>
        <p>{t(lang, 'season.intro')}</p>
      </header>

      <section className="live-card" aria-label={t(lang, 'season.simulate')}>
        <div className="season-bar">
          <button type="button" className="btn live-start" disabled={busy || simulating} onClick={simulate}>{t(lang, 'season.simulate')}</button>
          {view?.seasonId && <span className="muted">{view.seasonId} · {t(lang, 'season.progress').replace('{done}', String(view.done)).replace('{total}', String(view.total))}</span>}
        </div>
        {view?.seasonId && (
          <div className="season-progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            <span style={{ width: `${pct}%` }} />
          </div>
        )}
        {simulating && <p role="status" className="hint">{t(lang, 'season.simulating')}</p>}
        {!view && <p role="status" className="hint">{t(lang, 'live.waking')}</p>}
        {view && !view.seasonId && <p role="status" className="hint">{t(lang, 'season.none')}</p>}
        {note && <p role="status" className="hint">{note}</p>}
      </section>

      {view?.seasonId && (
        <div className="season-cols">
          <section className="live-card" aria-label={t(lang, 'season.table')}>
            <h2>{t(lang, 'season.table')}</h2>
            <p className="muted season-note">{t(lang, 'season.table.simulated')}</p>
            <div className="season-scroll"><SeasonTable rows={view.standings} clubs={view.clubs} lang={lang} /></div>
          </section>
          <section className="live-card" aria-label={t(lang, 'season.fixtures')}>
            <h2>{t(lang, 'season.fixtures')}</h2>
            <div className="season-rounds">
              {[...rounds.entries()].map(([n, fx]) => (
                <div key={n} className="season-round">
                  <h3>{t(lang, 'season.round').replace('{n}', String(n))}</h3>
                  <ul>
                    {fx.map((f) => (
                      <li key={f.id} className={`season-fx ${f.status}`}>
                        <span className="season-fx-name">{fixtureLabel(f, view.clubs)}{f.scenario ? <em className="season-story"> · {t(lang, 'season.story')}</em> : null}</span>
                        <span className="season-fx-score">
                          {f.status === 'done' && f.score ? `${f.score[f.home] ?? 0} – ${f.score[f.away] ?? 0}` : f.status === 'simulating' ? t(lang, 'season.running') : t(lang, 'season.pending')}
                        </span>
                        {f.status === 'done' && <button type="button" className={`chip${view.aired.includes(f.id) ? ' aired' : ''}`} onClick={() => void watch(f.id)}>{view.aired.includes(f.id) ? `✓ ${t(lang, 'season.watch')}` : t(lang, 'season.watch')}</button>}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
    </main>
  )
}

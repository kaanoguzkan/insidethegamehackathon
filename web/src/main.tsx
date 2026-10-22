import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { OpsPage } from './components/OpsPage'
import { PipelinePage } from './components/PipelinePage'
import '@fontsource-variable/archivo/wdth.css'
import './styles.css'

const page = () => (window.location.hash.startsWith('#ops') ? 'ops' : window.location.hash.startsWith('#pipeline') ? 'pipeline' : 'app')

/** The match center, the Operations page at ``#ops`` or the cloud pipeline at ``#pipeline``. */
function Root() {
  const [view, setView] = useState(page)
  useEffect(() => {
    const on = () => setView(page())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return view === 'ops' ? <OpsPage /> : view === 'pipeline' ? <PipelinePage /> : <App />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)

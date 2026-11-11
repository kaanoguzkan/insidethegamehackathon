import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { ArchitecturePage } from './components/ArchitecturePage'
import { OpsPage } from './components/OpsPage'
import { PipelinePage } from './components/PipelinePage'
import { VideoPage } from './components/VideoPage'
import '@fontsource-variable/archivo/wdth.css'
import './styles.css'

const page = () => (window.location.hash.startsWith('#ops') ? 'ops' : window.location.hash.startsWith('#pipeline') ? 'pipeline' : window.location.hash.startsWith('#architecture') ? 'architecture' : window.location.hash.startsWith('#video') ? 'video' : 'app')

/** The match center, or a page of its own: ``#ops`` Operations, ``#pipeline`` the cloud pipeline, ``#architecture`` the figures. */
function Root() {
  const [view, setView] = useState(page)
  useEffect(() => {
    const on = () => setView(page())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return view === 'ops' ? <OpsPage /> : view === 'pipeline' ? <PipelinePage /> : view === 'architecture' ? <ArchitecturePage /> : view === 'video' ? <VideoPage /> : <App />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)

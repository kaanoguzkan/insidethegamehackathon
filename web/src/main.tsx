import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { OpsPage } from './components/OpsPage'
import '@fontsource-variable/archivo/wdth.css'
import './styles.css'

const isOps = () => window.location.hash.startsWith('#ops')

/** The match center, or the Operations page at ``#ops``. */
function Root() {
  const [ops, setOps] = useState(isOps)
  useEffect(() => {
    const on = () => setOps(isOps())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return ops ? <OpsPage /> : <App />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)

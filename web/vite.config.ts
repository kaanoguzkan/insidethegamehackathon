import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// `base: './'` keeps asset URLs relative so the same build works on Static Web Apps (root) and on
// the GitHub Pages fallback mirror (served from /<repo>/).
// The Brain API address for the browser. VITE_BRAIN_URL wins; `azd` exposes the deployed Brain as BRAIN_URI, so a build
// run by `azd deploy` points at it without extra setup. With neither, the app plays recorded replays only.
const brain = process.env.VITE_BRAIN_URL ?? process.env.BRAIN_URI ?? ''

export default defineConfig({
  base: './',
  define: { 'import.meta.env.VITE_BRAIN_URL': JSON.stringify(brain) },
  plugins: [react()],
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
})

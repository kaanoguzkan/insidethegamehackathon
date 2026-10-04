// Copies the committed replay packages from ../data/replays into public/replays and writes an
// index.json listing them, so `vite` serves them in dev and `vite build` ships them.
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const src = join(here, '..', '..', 'data', 'replays')
const dst = join(here, '..', 'public', 'replays')

if (!existsSync(src)) {
  console.error(`no replay packages in ${src}; run: uv run matchmind build-replay pressing-collapse`)
  process.exit(1)
}
rmSync(dst, { recursive: true, force: true })
mkdirSync(dst, { recursive: true })
const index = []
for (const name of readdirSync(src, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name)) {
  cpSync(join(src, name), join(dst, name), { recursive: true })
  const manifest = JSON.parse(readFileSync(join(src, name, 'manifest.json'), 'utf8'))
  const meta = JSON.parse(readFileSync(join(src, name, 'meta.json'), 'utf8'))
  index.push({
    id: name,
    title: `${meta.home.name} v ${meta.away.name}`,
    score: meta.score,
    home: meta.home.id,
    away: meta.away.id,
    moments: manifest.moments,
    overlays: manifest.overlays,
  })
}
writeFileSync(join(dst, 'index.json'), JSON.stringify(index, null, 1))
console.log(`synced ${index.length} replay packages -> public/replays`)

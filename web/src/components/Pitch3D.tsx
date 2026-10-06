import { useEffect, useRef, type MutableRefObject } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import type { Replay } from '../lib/data'
import { drawGraphic, drawLayers, type Labels, type Layers } from '../lib/layers'
import { relax } from '../lib/spacing'
import type { Cam } from '../lib/webgl'
import type { MatchEvent, Overlay, TeamMeta } from '../lib/types'
import { drawEvidence, drawPitch, drawTag, L, PAD, SPRINT_TAG_KMH, W, type PitchBadge } from './Pitch'

const TEX_W = 1800
const TEX_H = Math.round((TEX_W * (W + PAD * 2)) / (L + PAD * 2))
const SCALE = 2.0 // players are drawn a little larger than life so they read at broadcast distance
const MIN_SEP = 2.4 // metres: figures are drawn at least this far apart (display only)
const GROUND_FPS = 15 // how often the ground texture is repainted while a live graphic is on it

interface Props {
  replay: Replay
  msRef: MutableRefObject<number>
  focusPlayer: string | null
  evidence: MatchEvent[] | null
  badges: PitchBadge[]
  layers: Layers
  graphics: Overlay[]
  labels: Labels
  highContrast: boolean
  reducedMotion: boolean
  label: string
  cam: Exclude<Cam, '2d'>
  follow: boolean
  onFail: () => void
}

/** Where a camera preset sits: a direction from the middle of the pitch and a distance that fits what it shows. */
function preset(cam: Exclude<Cam, '2d'>, aspect: number, fovDeg: number) {
  const hfov = 2 * Math.atan(Math.tan((fovDeg * Math.PI) / 360) * aspect)
  const fitLength = (L + 10) / (2 * Math.tan(hfov / 2)) // the whole length across the view
  const [az, el, dist] = cam === 'bc' ? [0, 47, fitLength * 1.06] : cam === 'end' ? [-90, 26, 92] : [0, 88, fitLength * 1.02]
  const a = (az * Math.PI) / 180
  const e = (el * Math.PI) / 180
  return { dir: new THREE.Vector3(Math.cos(e) * Math.sin(a), Math.sin(e), Math.cos(e) * Math.cos(a)), dist }
}

export default function Pitch3D(props: Props) {
  const wrap = useRef<HTMLDivElement>(null)
  const latest = useRef(props)
  latest.current = props
  const { replay, msRef } = props

  useEffect(() => {
    const el = wrap.current
    if (!el) return
    let renderer: THREE.WebGLRenderer
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' })
    } catch {
      latest.current.onFail()
      return
    }
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1))
    const gl = renderer.domElement
    gl.className = 'p3d-gl'
    el.appendChild(gl)
    const labelsCv = document.createElement('canvas')
    labelsCv.className = 'p3d-labels'
    el.appendChild(labelsCv)
    const lctx = labelsCv.getContext('2d')!
    const onLost = (e: Event) => {
      e.preventDefault()
      latest.current.onFail()
    }
    gl.addEventListener('webglcontextlost', onLost)

    const { meta, tracking } = replay
    const teamOf = (id: string): TeamMeta => (id.startsWith(meta.home.id) ? meta.home : meta.away)
    const info = (id: string) => teamOf(id).players[id]

    // ----- scene ---------------------------------------------------------------------------------------
    const scene = new THREE.Scene()
    scene.background = new THREE.Color('#080d0a')
    scene.fog = new THREE.Fog('#080d0a', 150, 330)
    scene.add(new THREE.HemisphereLight('#dfeaff', '#1b2b21', 1.15))
    const sun = new THREE.DirectionalLight('#fff6e0', 1.1)
    sun.position.set(-40, 90, 50)
    scene.add(sun)

    const camera = new THREE.PerspectiveCamera(42, 1.5, 1, 600)
    const controls = new OrbitControls(camera, gl)
    controls.enableDamping = true
    controls.dampingFactor = 0.09
    controls.enablePan = false
    controls.maxPolarAngle = THREE.MathUtils.degToRad(86)
    controls.minDistance = 14
    controls.maxDistance = 190
    controls.zoomSpeed = 0.8
    controls.rotateSpeed = 0.7

    // The ground is the 2D pitch drawing (lines, stripes, live graphics) used as a texture.
    const gcv = document.createElement('canvas')
    gcv.width = TEX_W
    gcv.height = TEX_H
    const gctx = gcv.getContext('2d')!
    const tex = new THREE.CanvasTexture(gcv)
    tex.colorSpace = THREE.SRGBColorSpace
    tex.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy())
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(L + PAD * 2, W + PAD * 2), new THREE.MeshBasicMaterial({ map: tex }))
    ground.rotation.x = -Math.PI / 2
    scene.add(ground)
    const apron = new THREE.Mesh(new THREE.PlaneGeometry(520, 420), new THREE.MeshLambertMaterial({ color: '#0b1410' }))
    apron.rotation.x = -Math.PI / 2
    apron.position.y = -0.05
    scene.add(apron)

    const disposables: { dispose: () => void }[] = [tex, renderer, controls]
    const geo = <T extends THREE.BufferGeometry>(g: T): T => {
      disposables.push(g)
      return g
    }
    const mat = <T extends THREE.Material>(m: T): T => {
      disposables.push(m)
      return m
    }

    // Goals, corner flags and a ring of stands.
    const post = mat(new THREE.MeshLambertMaterial({ color: '#f4f6f4' }))
    for (const side of [-1, 1]) {
      const x = (side * L) / 2
      for (const z of [-3.66, 3.66]) {
        const p = new THREE.Mesh(geo(new THREE.CylinderGeometry(0.07, 0.07, 2.44, 8)), post)
        p.position.set(x, 1.22, z)
        scene.add(p)
      }
      const bar = new THREE.Mesh(geo(new THREE.CylinderGeometry(0.07, 0.07, 7.4, 8)), post)
      bar.rotation.x = Math.PI / 2
      bar.position.set(x, 2.44, 0)
      scene.add(bar)
      const net = new THREE.Mesh(geo(new THREE.BoxGeometry(2.2, 2.44, 7.32)), mat(new THREE.MeshBasicMaterial({ color: '#ffffff', wireframe: true, transparent: true, opacity: 0.16 })))
      net.position.set(x + side * 1.1, 1.22, 0)
      scene.add(net)
    }
    const flag = mat(new THREE.MeshLambertMaterial({ color: '#ffd24a' }))
    for (const sx of [-1, 1]) {
      for (const sz of [-1, 1]) {
        const f = new THREE.Mesh(geo(new THREE.CylinderGeometry(0.04, 0.04, 1.6, 6)), flag)
        f.position.set((sx * L) / 2, 0.8, (sz * W) / 2)
        scene.add(f)
      }
    }
    const tierA = mat(new THREE.MeshLambertMaterial({ color: '#1f2f26' }))
    const tierB = mat(new THREE.MeshLambertMaterial({ color: '#2a3f34' }))
    const stand = (w: number, d: number, x: number, z: number, ry: number) => {
      for (let i = 0; i < 4; i++) {
        const b = new THREE.Mesh(geo(new THREE.BoxGeometry(w, 1.6, d - i * 2.2)), i % 2 ? tierA : tierB)
        b.position.y = 0.8 + i * 1.6
        const g = new THREE.Group()
        g.add(b)
        b.position.z = (i * 2.2) / 2 // each tier steps back
        g.position.set(x, 0, z)
        g.rotation.y = ry
        scene.add(g)
      }
    }
    stand(L + 30, 12, 0, -(W / 2 + PAD + 4), Math.PI) // far touchline, tiers rise away from the pitch
    stand(L + 30, 12, 0, W / 2 + PAD + 4, 0)
    stand(W + 20, 12, -(L / 2 + PAD + 4), 0, -Math.PI / 2)
    stand(W + 20, 12, L / 2 + PAD + 4, 0, Math.PI / 2)

    // ----- players and ball ---------------------------------------------------------------------------------
    interface Actor {
      group: THREE.Group
      ring: THREE.Mesh
      focus: THREE.Mesh
      heading: number
    }
    const bodyGeo = geo(new THREE.CapsuleGeometry(0.27, 0.85, 4, 10))
    const headGeo = geo(new THREE.SphereGeometry(0.17, 12, 10))
    const shoulderGeo = geo(new THREE.BoxGeometry(0.66, 0.2, 0.3))
    const shadowGeo = geo(new THREE.CircleGeometry(0.62, 20))
    const ringGeoHome = geo(new THREE.TorusGeometry(0.46, 0.035, 6, 24))
    const ringGeoAway = geo(new THREE.TorusGeometry(0.46, 0.09, 6, 24))
    const focusGeo = geo(new THREE.TorusGeometry(0.78, 0.07, 6, 28))
    const skin = mat(new THREE.MeshLambertMaterial({ color: '#d7b595' }))
    const whiteBasic = mat(new THREE.MeshBasicMaterial({ color: '#ffffff' }))
    const goldBasic = mat(new THREE.MeshBasicMaterial({ color: '#ffd24a' }))
    const shadowMat = mat(new THREE.MeshBasicMaterial({ color: '#000000', transparent: true, opacity: 0.38, depthWrite: false }))
    const actors: Actor[] = []
    const kits = new Map<string, { body: THREE.Material; shoulder: THREE.Material }>()
    const kit = (team: TeamMeta, gk: boolean) => {
      const key = `${team.id}${gk ? 'g' : ''}`
      let k = kits.get(key)
      if (!k) {
        const c = new THREE.Color(gk ? team.colors.secondary : team.colors.primary)
        k = { body: mat(new THREE.MeshLambertMaterial({ color: c })), shoulder: mat(new THREE.MeshLambertMaterial({ color: c.clone().lerp(new THREE.Color('#ffffff'), 0.28) })) }
        kits.set(key, k)
      }
      return k
    }
    for (let slot = 0; slot < 22; slot++) {
      const team = slot < 11 ? meta.home : meta.away
      const gk = slot % 11 === 0
      const k = kit(team, gk)
      const g = new THREE.Group()
      const body = new THREE.Mesh(bodyGeo, k.body)
      body.position.y = 0.93
      const shoulders = new THREE.Mesh(shoulderGeo, k.shoulder)
      shoulders.position.y = 1.36
      const head = new THREE.Mesh(headGeo, skin)
      head.position.y = 1.82
      const shadow = new THREE.Mesh(shadowGeo, shadowMat)
      shadow.rotation.x = -Math.PI / 2
      shadow.position.y = 0.02
      shadow.scale.setScalar(1 / SCALE) // the group is scaled up; the shadow stays true to size
      const ring = new THREE.Mesh(slot < 11 ? ringGeoHome : ringGeoAway, whiteBasic)
      ring.rotation.x = Math.PI / 2
      ring.position.y = 0.05
      const focus = new THREE.Mesh(focusGeo, goldBasic)
      focus.rotation.x = Math.PI / 2
      focus.position.y = 0.07
      focus.visible = false
      g.add(shadow, body, shoulders, head, ring, focus)
      g.scale.setScalar(SCALE)
      g.visible = false
      scene.add(g)
      actors.push({ group: g, ring, focus, heading: slot < 11 ? Math.PI / 2 : -Math.PI / 2 })
    }
    const ball = new THREE.Mesh(geo(new THREE.SphereGeometry(0.4, 16, 12)), mat(new THREE.MeshLambertMaterial({ color: '#ffffff' })))
    scene.add(ball)
    const ballShadow = new THREE.Mesh(shadowGeo, shadowMat)
    ballShadow.rotation.x = -Math.PI / 2
    scene.add(ballShadow)

    // ----- camera ---------------------------------------------------------------------------------------------
    let size = { w: 1, h: 1 }
    let wantCam = latest.current.cam
    let appliedCam: string | null = null
    let tween = 0
    const goalPos = new THREE.Vector3()
    const goalTarget = new THREE.Vector3()
    const applyPreset = () => {
      const p = preset(wantCam, size.w / size.h, camera.fov)
      goalTarget.set(0, 0, wantCam === 'bc' ? 2 : 0)
      goalPos.copy(goalTarget).addScaledVector(p.dir, p.dist)
      if (wantCam === 'top') goalPos.z += 0.01
      tween = 1
      appliedCam = wantCam
    }
    controls.addEventListener('start', () => {
      tween = 0
    })
    const resize = () => {
      const w = Math.max(1, el.clientWidth)
      const h = Math.max(1, el.clientHeight)
      size = { w, h }
      renderer.setSize(w, h, false)
      gl.style.width = '100%'
      gl.style.height = '100%'
      const dpr = Math.min(2, window.devicePixelRatio || 1)
      labelsCv.width = Math.round(w * dpr)
      labelsCv.height = Math.round(h * dpr)
      labelsCv.style.width = '100%'
      labelsCv.style.height = '100%'
      lctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      applyPreset()
      camera.position.copy(goalPos)
      controls.target.copy(goalTarget)
      tween = 0
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(el)

    // ----- the loop -----------------------------------------------------------------------------------------------
    const tmp = new THREE.Vector3()
    const prevHeading: number[] = actors.map((a) => a.heading)
    const offs = actors.map(() => ({ x: 0, y: 0 })) // each figure's current display offset from its true position
    let lastGround = 0
    let lastKey = ''
    let raf = 0
    const draw = (now: number) => {
      const p = latest.current
      if (p.cam !== wantCam || appliedCam !== p.cam) {
        wantCam = p.cam
        applyPreset()
      }
      const ms = msRef.current
      const f = tracking.at(ms)
      const prev = tracking.at(Math.max(0, ms - 200))
      const prevById = new Map(prev.players.map((q) => [q.id, q]))

      // Ball carrier: the closest player to a live ball.
      let carrier: string | null = null
      let carrierPoint: (typeof f.players)[number] | null = null
      if (f.ball.alive) {
        let best = 2.6
        for (const q of f.players) {
          const d = Math.hypot(q.x - f.ball.x, q.y - f.ball.y)
          if (d < best) {
            best = d
            carrier = q.id
            carrierPoint = q
          }
        }
      }

      // Display positions: players the data puts almost on top of each other are drawn apart (smoothly).
      const sep = relax(f.players, MIN_SEP, carrier ? f.players.findIndex((q) => q.id === carrier) : -1, 3.4, 6, p.cam === 'bc' ? [1, 0.55] : p.cam === 'end' ? [0.55, 1] : [1, 1])
      const shown = f.players.map((q, i) => {
        const o = offs[q.slot] ?? { x: 0, y: 0 }
        o.x += (sep[i].x - q.x - o.x) * 0.4
        o.y += (sep[i].y - q.y - o.y) * 0.4
        return { x: q.x + o.x, y: q.y + o.y }
      })

      // Ground texture: repainted when a live graphic is on it, or when something that shapes it changed.
      const live = p.graphics.length > 0 || !!(p.evidence && p.evidence.length) || Object.values(p.layers).some(Boolean)
      const key = `${p.highContrast}|${Object.entries(p.layers).filter(([, v]) => v).map(([k]) => k).join()}|${p.graphics.length}|${p.evidence?.length ?? 0}`
      if ((live && now - lastGround > 1000 / GROUND_FPS) || key !== lastKey || lastKey === '') {
        lastKey = key
        lastGround = now
        const s = TEX_W / (L + PAD * 2)
        const tx = { X: (x: number) => (x + PAD) * s, Y: (y: number) => (y + PAD) * s, s }
        gctx.setTransform(1, 0, 0, 1, 0, 0)
        drawPitch(gctx, TEX_W, TEX_H, s, p.highContrast)
        drawLayers(gctx, replay, f, ms, p.layers, carrierPoint, tx, p.labels)
        for (const g of p.graphics) drawGraphic(gctx, g, ms, tx, p.reducedMotion)
        if (p.evidence && p.evidence.length) drawEvidence(gctx, p.evidence, meta.home.id, meta, tx.X, tx.Y, s)
        tex.needsUpdate = true
      }

      // Players: place, face the way they are moving, mark the followed one.
      const seen = new Set<number>()
      f.players.forEach((q, i) => {
        const a = actors[q.slot]
        if (!a) return
        seen.add(q.slot)
        a.group.visible = true
        a.group.position.set(shown[i].x - L / 2, 0, shown[i].y - W / 2)
        const pq = prevById.get(q.id)
        if (pq) {
          const dx = q.x - pq.x
          const dz = q.y - pq.y
          if (Math.hypot(dx, dz) > 0.25) {
            const want = Math.atan2(dx, dz)
            let d = want - prevHeading[q.slot]
            d = Math.atan2(Math.sin(d), Math.cos(d))
            prevHeading[q.slot] += d * 0.35
            a.group.rotation.y = prevHeading[q.slot]
          }
        }
        const isFocus = p.focusPlayer === q.id
        a.focus.visible = isFocus
        if (isFocus) a.focus.scale.setScalar(p.reducedMotion ? 1 : 1 + 0.12 * Math.sin(now / 260))
      })
      actors.forEach((a, i) => {
        if (!seen.has(i)) a.group.visible = false
      })
      ball.position.set(f.ball.x - L / 2, 0.4 + f.ball.z, f.ball.y - W / 2)
      ballShadow.position.set(f.ball.x - L / 2, 0.03, f.ball.y - W / 2)
      ballShadow.scale.setScalar(0.5 * (1 - Math.min(0.6, f.ball.z / 25)))

      // Camera: glide to the preset, optionally follow the ball along the pitch.
      if (tween > 0) {
        camera.position.lerp(goalPos, 0.1)
        controls.target.lerp(goalTarget, 0.1)
        if (camera.position.distanceTo(goalPos) < 0.2) tween = 0
      } else if (p.follow && p.cam !== 'top') {
        const want = THREE.MathUtils.clamp((f.ball.x - L / 2) * 0.62, -34, 34)
        const dx = (want - controls.target.x) * 0.06
        controls.target.x += dx
        camera.position.x += dx
      }
      controls.update()
      renderer.render(scene, camera)

      // Numbers and name tags, drawn flat over the scene at each player's projected head.
      const { w, h } = size
      lctx.clearRect(0, 0, w, h)
      const tags: { x: number; y: number; text: string; color: string; strong: boolean }[] = []
      f.players.forEach((q, i) => {
        const team = teamOf(q.id)
        const gk = q.slot % 11 === 0
        tmp.set(shown[i].x - L / 2, 2.1 * SCALE, shown[i].y - W / 2).project(camera)
        if (tmp.z > 1) return
        const sx = (tmp.x * 0.5 + 0.5) * w
        const sy = (-tmp.y * 0.5 + 0.5) * h
        const dist = camera.position.distanceTo(a3(shown[i].x - L / 2, shown[i].y - W / 2))
        const ppm = h / 2 / (Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) * dist)
        const r = Math.min(10, Math.max(5.5, ppm * 1.0))
        lctx.beginPath()
        lctx.arc(sx, sy, r, 0, Math.PI * 2)
        lctx.fillStyle = gk ? team.colors.secondary : team.colors.primary
        lctx.fill()
        lctx.lineWidth = team.id === meta.home.id ? 1.3 : 2.4
        lctx.strokeStyle = '#ffffff'
        lctx.stroke()
        if (r >= 7) {
          lctx.fillStyle = gk ? team.colors.primary : team.colors.secondary
          lctx.font = `700 ${Math.round(r * 0.95)}px system-ui, sans-serif`
          lctx.textAlign = 'center'
          lctx.textBaseline = 'middle'
          lctx.fillText(String(info(q.id)?.number ?? ''), sx, sy + 0.5)
        }
        const isFocus = p.focusPlayer === q.id
        if (q.id === carrier || isFocus) {
          const pq = prevById.get(q.id)
          const kmh = pq && f.ball.alive ? (Math.hypot(q.x - pq.x, q.y - pq.y) / 0.2) * 3.6 : 0
          const nm = info(q.id)?.name?.split(' ').slice(-1)[0] ?? q.id
          tags.push({ x: sx, y: sy - r - 6, text: kmh >= SPRINT_TAG_KMH ? `${nm}  ${kmh.toFixed(0)} km/h` : nm, color: team.colors.primary, strong: isFocus })
        }
      })
      for (const b of p.badges) {
        const bi = f.players.findIndex((z) => z.id === b.playerId)
        if (bi < 0) continue
        tmp.set(shown[bi].x - L / 2, 2.1 * SCALE + 1.2, shown[bi].y - W / 2).project(camera)
        if (tmp.z > 1) continue
        tags.push({ x: (tmp.x * 0.5 + 0.5) * w, y: (-tmp.y * 0.5 + 0.5) * h - 18, text: b.text, color: '#ffb454', strong: true })
      }
      for (const t of tags) drawTag(lctx, t.x, t.y, t.text, t.color, t.strong, w)
      if (!f.ball.alive) {
        lctx.fillStyle = 'rgba(255,255,255,.7)'
        lctx.font = '600 11px system-ui, sans-serif'
        lctx.textAlign = 'left'
        lctx.fillText('BALL OUT', 10, h - 10)
      }
      raf = requestAnimationFrame(draw)
    }
    const probe = new THREE.Vector3()
    const a3 = (x: number, z: number) => probe.set(x, 0, z)
    raf = requestAnimationFrame(draw)

    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      gl.removeEventListener('webglcontextlost', onLost)
      disposables.forEach((d) => d.dispose())
      renderer.forceContextLoss()
      el.replaceChildren()
    }
  }, [replay, msRef])

  return (
    <div ref={wrap} className="pitch-wrap pitch-3d" role="img" aria-label={props.label}>
      {/* the WebGL canvas and the label canvas are added by the effect */}
    </div>
  )
}

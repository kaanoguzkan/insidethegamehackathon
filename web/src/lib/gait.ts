/**
 * How a stylised player moves, from what the tracking gives (a speed and a heading) and the events (a pass or a shot). Angles are in radians with
 * "forward" positive; the drawing code decides what that means for each joint. No three.js here, so it can be tested.
 */

export interface Gait {
  hipL: number
  hipR: number
  kneeL: number
  kneeR: number
  armL: number
  armR: number
  /** Forward lean of the body. */
  lean: number
  /** How far the body rises and falls with each stride, in metres. */
  bob: number
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

/** The speed (m/s) at which the stride is at its fullest. */
export const FULL_STRIDE_MS = 7

/** How much the phase of the stride advances for a distance covered: one step (half a cycle) for about 1.2 m, capped so a fast-forwarded match does not strobe. */
export function strideAdvance(distance: number): number {
  return Math.min(0.9, (Math.max(0, distance) / 1.2) * Math.PI)
}

/** 0 at rest, 1 at a full run: how big the movements are. A slow walk is already visibly a walk. */
export function effort(speed: number): number {
  if (speed < 0.35) return 0
  return clamp(0.22 + 0.78 * (speed / FULL_STRIDE_MS), 0, 1)
}

/**
 * The pose for a speed and a point in the stride. ``kick`` is how far into a kick the player is (0: not kicking, 1: the foot is through the ball);
 * the kicking leg is the right one.
 */
export function gait(speed: number, phase: number, kick = 0): Gait {
  const e = effort(speed)
  const swing = 0.95 * e
  const s = Math.sin(phase)
  const c = Math.cos(phase)
  const flex = e === 0 ? 0 : 0.25 + 1.0 * e
  let hipL = swing * s
  let hipR = -swing * s
  let kneeL = flex * Math.max(0, c)
  let kneeR = flex * Math.max(0, -c)
  let armL = 0.9 * swing * s // each arm swings with the opposite leg
  let armR = -0.9 * swing * s
  let lean = 0.04 + 0.3 * e
  if (kick > 0) {
    const k = clamp(kick, 0, 1)
    hipR += (1.5 - hipR) * k // the right leg swings through
    kneeR += (0.15 - kneeR) * k // and straightens as it meets the ball
    kneeL = Math.max(kneeL, 0.4 * k) // the standing leg takes the weight
    hipL += (-0.15 - hipL) * k
    armL += (0.9 - armL) * k
    armR += (-0.8 - armR) * k
    lean -= 0.12 * k
  }
  return { hipL, hipR, kneeL, kneeR, armL, armR, lean, bob: 0.03 * e * Math.abs(c) }
}

/** The envelope of a kick: how far through the movement a player is, ``sinceMs`` after the event (negative: the wind-up before it). 0 outside the window. */
export function kickPhase(sinceMs: number, windowMs: number): number {
  const lead = windowMs * 0.35 // the backswing starts before the ball leaves the foot
  const t = (sinceMs + lead) / windowMs
  return t <= 0 || t >= 1 ? 0 : Math.sin(Math.PI * t)
}

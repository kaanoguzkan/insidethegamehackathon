/** Whether this browser can draw WebGL at all; the 3D pitch falls back to the flat one when it cannot. */
let supported: boolean | undefined

export function webglSupported(): boolean {
  if (supported !== undefined) return supported // asked on every render of the strip: a context per ask would leak
  try {
    const c = document.createElement('canvas')
    supported = !!(c.getContext('webgl2') || c.getContext('webgl'))
  } catch {
    supported = false
  }
  return supported
}

export type Cam = '2d' | 'bc' | 'end' | 'top'
export const CAMS: Cam[] = ['2d', 'bc', 'end', 'top']

/** Whether this browser can draw WebGL at all; the 3D pitch falls back to the flat one when it cannot. */
export function webglSupported(): boolean {
  try {
    const c = document.createElement('canvas')
    return !!(c.getContext('webgl2') || c.getContext('webgl'))
  } catch {
    return false
  }
}

export type Cam = '2d' | 'bc' | 'end' | 'top'
export const CAMS: Cam[] = ['2d', 'bc', 'end', 'top']

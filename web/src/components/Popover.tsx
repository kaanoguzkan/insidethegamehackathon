import { useEffect, useId, useRef, useState, type ReactNode } from 'react'

interface Props {
  /** What the button says. */
  label: ReactNode
  /** Accessible name for the panel; defaults to the label text. */
  title: string
  children: ReactNode
  align?: 'start' | 'end'
  placement?: 'below' | 'above'
  className?: string
  badge?: ReactNode
  /** Controlled open state, for callers that need to close the panel themselves. */
  onToggle?: (open: boolean) => void
}

/** A button that opens a small panel next to it. Closes on outside click and Escape. */
export function Popover({ label, title, children, align = 'end', placement = 'below', className = '', badge, onToggle }: Props) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const id = useId()
  const set = (v: boolean) => {
    setOpen(v)
    onToggle?.(v)
  }
  useEffect(() => {
    if (!open) return
    const down = (e: PointerEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) set(false)
    }
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        set(false)
        root.current?.querySelector('button')?.focus()
      }
    }
    document.addEventListener('pointerdown', down)
    document.addEventListener('keydown', key, true)
    return () => {
      document.removeEventListener('pointerdown', down)
      document.removeEventListener('keydown', key, true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
  return (
    <div className={`pop ${className}`} ref={root}>
      <button type="button" className={`btn pop-btn${open ? ' on' : ''}`} aria-expanded={open} aria-controls={id} aria-haspopup="dialog" onClick={() => set(!open)}>
        {label}
        {badge}
      </button>
      {open && (
        <div id={id} role="dialog" aria-label={title} className={`pop-panel ${align} ${placement}`}>
          {children}
        </div>
      )}
    </div>
  )
}

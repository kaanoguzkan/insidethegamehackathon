/** A bar that fills over the time a live answer usually takes, so the wait looks like work in progress. It never claims to be done: it stops short and waits. */
export function LoadBar({ seconds = 6 }: { seconds?: number }) {
  return (
    <div className="loadbar" aria-hidden="true">
      <span style={{ animationDuration: `${seconds}s` }} />
    </div>
  )
}

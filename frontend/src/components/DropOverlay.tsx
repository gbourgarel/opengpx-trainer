/** The drop zone shown while files are dragged over the window (see useFileDrop). */
export function DropOverlay({ text }: { text: string }) {
  return (
    <div className="drop-overlay" aria-hidden>
      <div>{text}</div>
    </div>
  )
}

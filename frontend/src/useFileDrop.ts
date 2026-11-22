import { useEffect, useRef, useState } from 'react'
import { carriesFiles, splitByExtension } from './fileDrop'

/** Files dragged anywhere onto the window while the component using it is shown: returns
 * whether a drag is over the window (to show the drop zone); on drop, `onDrop` gets the files
 * with one of `exts` and the names of the others. The browser never opens a dropped file. */
export function useFileDrop(exts: readonly string[], onDrop: (accepted: File[], refused: string[]) => void): boolean {
  const [dragging, setDragging] = useState(false)
  const onDropRef = useRef(onDrop)
  useEffect(() => {
    onDropRef.current = onDrop // the latest handler, without re-adding the listeners
  })
  const extsKey = exts.join(',')
  useEffect(() => {
    const list = extsKey.split(',')
    let depth = 0 // dragenter / dragleave also fire for every child element crossed
    const enter = (e: DragEvent) => {
      if (!carriesFiles(e.dataTransfer?.types)) return
      e.preventDefault()
      depth += 1
      setDragging(true)
    }
    const over = (e: DragEvent) => {
      if (!carriesFiles(e.dataTransfer?.types)) return
      e.preventDefault() // allows the drop
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
    }
    const leave = (e: DragEvent) => {
      if (!carriesFiles(e.dataTransfer?.types)) return
      depth = Math.max(0, depth - 1)
      if (depth === 0) setDragging(false)
    }
    const drop = (e: DragEvent) => {
      if (!carriesFiles(e.dataTransfer?.types)) return
      e.preventDefault()
      depth = 0
      setDragging(false)
      const { accepted, refused } = splitByExtension(Array.from(e.dataTransfer?.files ?? []), list)
      onDropRef.current(accepted, refused)
    }
    window.addEventListener('dragenter', enter)
    window.addEventListener('dragover', over)
    window.addEventListener('dragleave', leave)
    window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('dragenter', enter)
      window.removeEventListener('dragover', over)
      window.removeEventListener('dragleave', leave)
      window.removeEventListener('drop', drop)
    }
  }, [extsKey])
  return dragging
}

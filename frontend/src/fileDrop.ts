/* Files dropped onto a tab (e.g. .gpx on Routes): which ones to import. Pure functions; the
 * hook listening to the window is in components/FileDrop.tsx. */

/** A drag carries files (not text or a link dragged from the page). */
export function carriesFiles(types: readonly string[] | null | undefined): boolean {
  return !!types && Array.from(types).includes('Files')
}

/** Files whose extension is one of `exts` (lower case, with the dot), in the order dropped,
 * and the names of the others. */
export function splitByExtension<F extends { name: string }>(files: readonly F[], exts: readonly string[]): { accepted: F[]; refused: string[] } {
  const accepted: F[] = []
  const refused: string[] = []
  for (const f of files) {
    const dot = f.name.lastIndexOf('.')
    const ext = dot < 0 ? '' : f.name.slice(dot).toLowerCase()
    if (exts.includes(ext)) accepted.push(f)
    else refused.push(f.name)
  }
  return { accepted, refused }
}

// The user guide shown in the Help tab: docs/guide.md and docs/guide.fr.md, rendered with
// marked (the same files as on GitHub, bundled at build time).

export type GuideLang = 'en' | 'fr'

/** The guide's language: the one chosen in this browser, else the first of the browser's
 * preferred languages that has a guide (`navigator.languages`), else English. */
export function guideLang(saved: string | null, languages: readonly string[]): GuideLang {
  if (saved === 'en' || saved === 'fr') return saved
  for (const l of languages) {
    const base = l.toLowerCase().split('-')[0]
    if (base === 'fr' || base === 'en') return base
  }
  return 'en'
}

/** Links to other sites open in a new tab: the app's tab keeps the ride. */
export function externalLinks(html: string): string {
  return html.replace(/<a href="(https?:\/\/[^"]*)"/g, '<a href="$1" target="_blank" rel="noopener noreferrer"')
}

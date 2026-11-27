import { useMemo, useState } from 'react'
import { marked } from 'marked'
import guideEn from '../../../docs/guide.md?raw'
import guideFr from '../../../docs/guide.fr.md?raw'
import { externalLinks, guideLang, type GuideLang } from '../help'
import { getSetting, setSetting } from '../localSettings'

const GUIDES: Record<GuideLang, string> = { en: guideEn, fr: guideFr }
const OTHER: Record<GuideLang, { lang: GuideLang; label: string }> = {
  en: { lang: 'fr', label: 'Français' },
  fr: { lang: 'en', label: 'English' },
}

function initialLang(): GuideLang {
  let saved: string | null = null
  try {
    saved = getSetting('guideLang')
  } catch {
    // storage unavailable: the browser's language
  }
  return guideLang(saved, typeof navigator !== 'undefined' ? navigator.languages : [])
}

/** The user guide (docs/guide*.md), in English or French. */
export function HelpPage() {
  const [lang, setLang] = useState(initialLang)
  // our own Markdown, bundled at build time: trusted
  const html = useMemo(() => externalLinks(marked.parse(GUIDES[lang], { async: false })), [lang])
  const other = OTHER[lang]
  const switchTo = () => {
    setLang(other.lang)
    try {
      setSetting('guideLang', other.lang)
    } catch {
      // not remembered: fine
    }
  }
  return (
    <div className="card help">
      <button className="ghost help-lang" onClick={switchTo} lang={other.lang}>
        {other.label}
      </button>
      <div className="help-body" lang={lang} dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  )
}

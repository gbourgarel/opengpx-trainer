import assert from 'node:assert/strict'
import { externalLinks, guideLang } from '../src/help'

export const checks = {
  'a language chosen in this browser wins': () => {
    assert.equal(guideLang('en', ['fr-FR']), 'en')
    assert.equal(guideLang('fr', ['en-US']), 'fr')
  },
  'else the first preferred language that has a guide': () => {
    assert.equal(guideLang(null, ['fr-FR', 'en-US']), 'fr')
    assert.equal(guideLang(null, ['de-DE', 'FR', 'en']), 'fr')
    assert.equal(guideLang(null, ['en-GB', 'fr']), 'en')
  },
  'else English (unknown language, nothing stored, or a stale value)': () => {
    assert.equal(guideLang(null, ['de-DE']), 'en')
    assert.equal(guideLang(null, []), 'en')
    assert.equal(guideLang('es', ['fr']), 'fr')
  },
  'only links to other sites open in a new tab': () => {
    const html = '<a href="https://intervals.icu">x</a> <a href="#first-setup">y</a>'
    assert.equal(
      externalLinks(html),
      '<a href="https://intervals.icu" target="_blank" rel="noopener noreferrer">x</a> <a href="#first-setup">y</a>',
    )
  },
}

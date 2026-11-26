import { OSM_TILES, tileLayer } from '../src/mapTiles.ts'

function eq(a: unknown, b: unknown, what: string) {
  if (a !== b) throw new Error(`${what}: ${JSON.stringify(a)} !== ${JSON.stringify(b)}`)
}

export const checks = {
  'empty URL falls back to openstreetmap.org with its credit'() {
    const t = tileLayer('  ', 'ignored')
    eq(t.url, OSM_TILES, 'url')
    if (!t.attribution.includes('OpenStreetMap')) throw new Error('OSM credit missing')
  },
  'a custom URL without credit is credited to its host'() {
    eq(tileLayer('https://tile.thunderforest.com/cycle/{z}/{x}/{y}.png?apikey=k', '').attribution, 'tile.thunderforest.com', 'credit')
  },
  'the credit text cannot inject HTML'() {
    eq(tileLayer('https://t.example/{z}/{x}/{y}.png', '<img src=x onerror=alert(1)>').attribution, '&lt;img src=x onerror=alert(1)&gt;', 'credit')
  },
}

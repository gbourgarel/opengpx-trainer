import { OSM_TILES, tileLayer, tileUrl } from '../src/mapTiles.ts'

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
  'a template is filled in its own order (Esri: z / y / x)'() {
    eq(tileUrl('https://t.example/tile/{z}/{y}/{x}?k=1', 12, 2100, 1460), 'https://t.example/tile/12/1460/2100?k=1', 'url')
  },
  'the credit text cannot inject HTML'() {
    eq(tileLayer('https://t.example/{z}/{x}/{y}.png', '<img src=x onerror=alert(1)>').attribution, '&lt;img src=x onerror=alert(1)&gt;', 'credit')
  },
}

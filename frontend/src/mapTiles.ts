/* Background of the 2D map: openstreetmap.org by default, or the XYZ tile URL set in Profile. */

export const OSM_TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const OSM_CREDIT = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

export const escapeHtml = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

/** URL of one tile from an XYZ template ({z}, {x}, {y}, in any order). */
export function tileUrl(template: string, z: number, x: number, y: number): string {
  return template.replaceAll('{z}', String(z)).replaceAll('{x}', String(x)).replaceAll('{y}', String(y))
}

/** Leaflet tile layer options; the attribution is HTML for Leaflet, so the user's text is escaped. */
export function tileLayer(url: string, attribution: string): { url: string; attribution: string } {
  if (!url.trim()) return { url: OSM_TILES, attribution: OSM_CREDIT }
  let credit = attribution.trim()
  if (!credit) {
    try {
      credit = new URL(url.replace(/[{}]/g, '')).hostname
    } catch {
      credit = 'custom tiles'
    }
  }
  return { url: url.trim(), attribution: escapeHtml(credit) }
}

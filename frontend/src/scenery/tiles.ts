// Tile sources of the 3D view, behind one MapLibre custom protocol ("ht://").
//
// * Imagery: IGN orthophotos (Géoplateforme WMTS, Licence Ouverte Etalab 2.0, no key) where IGN
//   has data, i.e. France; the service answers 404 elsewhere and the same tile is then taken
//   from Esri World Imagery. Chosen per tile, so a route crossing a border gets both.
// * Terrain: AWS Terrain Tiles (Terrarium encoding).
import type { AddProtocolAction } from 'maplibre-gl'

export const IMAGERY_URL = 'ht://sat/{z}/{x}/{y}'
export const DEM_URL = 'ht://dem/{z}/{x}/{y}'
export const IMAGERY_MAX_ZOOM = 19
export const DEM_MAX_ZOOM = 14
export const ATTRIBUTION =
  'Imagery © <a href="https://www.ign.fr/">IGN</a> (France), © Esri, Maxar, Earthstar Geographics · ' +
  'Terrain: Mapzen / AWS Terrain Tiles · Route © OpenStreetMap contributors'

const ign = (z: number, x: number, y: number) =>
  'https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=ORTHOIMAGERY.ORTHOPHOTOS' +
  `&STYLE=normal&TILEMATRIXSET=PM&FORMAT=image/jpeg&TILEMATRIX=${z}&TILEROW=${y}&TILECOL=${x}`
const esri = (z: number, x: number, y: number) =>
  `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${y}/${x}`
const terrarium = (z: number, x: number, y: number) =>
  `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/${z}/${x}/${y}.png`

/** Bytes of one tile; key = "sat/z/x/y" or "dem/z/x/y". */
export async function fetchTile(key: string, signal: AbortSignal): Promise<ArrayBuffer> {
  const [kind, zs, xs, ys] = key.split('/')
  const [z, x, y] = [Number(zs), Number(xs), Number(ys)]
  if (kind === 'dem') {
    const r = await fetch(terrarium(z, x, y), { signal })
    if (!r.ok) throw new Error(`terrain tile ${key}: ${r.status}`)
    return r.arrayBuffer()
  }
  if (z <= IMAGERY_MAX_ZOOM) {
    const r = await fetch(ign(z, x, y), { signal })
    if (r.ok) return r.arrayBuffer()
    if (r.status !== 404) throw new Error(`IGN tile ${key}: ${r.status}`)
  }
  const r = await fetch(esri(z, x, y), { signal }) // outside IGN's coverage
  if (!r.ok) throw new Error(`Esri tile ${key}: ${r.status}`)
  return r.arrayBuffer()
}

export const loadTile: AddProtocolAction = async (params, abortController) => ({
  data: await fetchTile(params.url.slice('ht://'.length), abortController.signal),
})

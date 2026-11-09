// Tile sources of the 3D view, behind one MapLibre custom protocol ("ht://").
//
// * Imagery: IGN orthophotos (Géoplateforme WMTS, Licence Ouverte Etalab 2.0, no key) where IGN
//   has data, i.e. France; the service answers 404 elsewhere and the same tile is then taken
//   from Esri World Imagery. Chosen per tile, so a route crossing a border gets both.
// * The finest level (z19, ~30 cm/px) is a bonus, IGN only: where IGN has no z19 tile the view
//   stays at z18 there (MapLibre shows the parent tile) rather than switching source for a
//   finer level (user's choice); and it is prefetched last, when the network keeps up.
// * Terrain: AWS Terrain Tiles (Terrarium encoding).
import type { AddProtocolAction } from 'maplibre-gl'

export const IMAGERY_URL = 'ht://sat/{z}/{x}/{y}'
export const DEM_URL = 'ht://dem/{z}/{x}/{y}'
export const IMAGERY_MAX_ZOOM = 19
const BONUS_ZOOM = 19

/** Thrown for a tile that does not exist at that level: MapLibre then keeps the parent tile. */
export class NoTile extends Error {
  constructor(key: string) {
    super(`no tile ${key} (coarser level shown)`)
    this.name = 'NoTile'
  }
}
const missing = new Set<string>() // tiles known not to exist: never asked again
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
  if (missing.has(key)) throw new NoTile(key)
  const r0 = await fetch(ign(z, x, y), { signal })
  if (r0.ok) return r0.arrayBuffer()
  if (r0.status !== 404) throw new Error(`IGN tile ${key}: ${r0.status}`)
  if (z >= BONUS_ZOOM) {
    missing.add(key) // no finer IGN tile here: stay at the coarser level, same source
    throw new NoTile(key)
  }
  const r = await fetch(esri(z, x, y), { signal }) // outside IGN's coverage
  if (!r.ok) throw new Error(`Esri tile ${key}: ${r.status}`)
  return r.arrayBuffer()
}

// ---- rolling prefetch --------------------------------------------------------------------
// The tiles of the next kilometre of the route are downloaded ahead, so fast riding (descents)
// does not outrun the network. Memory only: tiles left behind are dropped, and the whole cache
// is cleared when the view closes or the ride ends ("it is only a cache").

const cache = new Map<string, ArrayBuffer>()
const inflight = new Map<string, Promise<ArrayBuffer>>()
let generation = 0 // bumped by clearTileCache: late downloads are thrown away
let queue: string[] = []
let active = 0
const MAX_PARALLEL = 6

export const tileStats = {
  requests: 0,
  hits: 0,
  waits: 0,
  misses: 0,
  prefetched: 0,
  prefetchedBytes: 0,
  cachedTiles: 0,
  cachedBytes: 0,
  missesByLayer: {} as Record<string, number>, // "sat z17" -> count (tuning the corridor)
}

function download(key: string): Promise<ArrayBuffer> {
  let p = inflight.get(key)
  if (!p) {
    p = fetchTile(key, new AbortController().signal).finally(() => inflight.delete(key))
    inflight.set(key, p)
  }
  return p
}

/** MapLibre's tile loader: from the prefetch cache when there, else from the network. Always a
 *  copy: MapLibre transfers the buffer to a worker, which empties it. */
export const loadTile: AddProtocolAction = async (params, abortController) => {
  const key = params.url.slice('ht://'.length)
  tileStats.requests++
  const hit = cache.get(key)
  if (hit) {
    tileStats.hits++
    return { data: hit.slice(0) }
  }
  const pending = inflight.get(key)
  if (pending) {
    tileStats.waits++
    return { data: (await pending).slice(0) }
  }
  tileStats.misses++
  const [kind, z] = key.split('/')
  const layer = `${kind} z${z}`
  tileStats.missesByLayer[layer] = (tileStats.missesByLayer[layer] ?? 0) + 1
  return { data: await fetchTile(key, abortController.signal) }
}

export function tileOf(lng: number, lat: number, z: number): [number, number] {
  const n = 2 ** z
  return [Math.floor(((lng + 180) / 360) * n), Math.floor(((1 - Math.asinh(Math.tan((lat * Math.PI) / 180)) / Math.PI) / 2) * n)]
}

/**
 * Corridor along the route, per layer and zoom: radius in tiles around each point of the route
 * stretch, and how far ahead that zoom is needed. Measured in the spike: at every zoom the
 * camera asks for tiles up to 3-4 tiles from the route (p90); the finest levels only near it.
 * In the app the finest IGN level (z19, ~54 m tiles) needs a wider radius: the camera swings to
 * the outside of turns, up to ~80 m off the route (simulator descent: z19 made 84 of the 123
 * misses with radius 2).
 */
export const CORRIDOR: Record<'sat' | 'dem', Record<number, { radius: number; aheadM: number }>> = {
  sat: {
    19: { radius: 4, aheadM: 400 },
    18: { radius: 4, aheadM: 500 },
    17: { radius: 3, aheadM: 700 },
    16: { radius: 3, aheadM: 1000 },
    15: { radius: 3, aheadM: 1000 },
    14: { radius: 3, aheadM: 1000 },
    13: { radius: 3, aheadM: 1000 },
    12: { radius: 3, aheadM: 1000 },
    11: { radius: 2, aheadM: 1000 },
    10: { radius: 2, aheadM: 1000 },
  },
  dem: {
    14: { radius: 3, aheadM: 1000 },
    13: { radius: 3, aheadM: 1000 },
    12: { radius: 3, aheadM: 1000 },
    11: { radius: 3, aheadM: 1000 },
    10: { radius: 2, aheadM: 1000 },
    9: { radius: 2, aheadM: 1000 },
  },
}
export const BEHIND_M = 300

/** Tile keys wanted around the route stretch [s - behind, s + ahead], nearest first. */
export function wantedTiles(points: (s: number) => [number, number], s: number, total: number, stepM = 25): string[] {
  const order = new Map<string, number>()
  for (let d = Math.max(0, s - BEHIND_M); d <= Math.min(total, s + 1000); d += stepM) {
    const [lng, lat] = points(d)
    for (const kind of ['sat', 'dem'] as const) {
      for (const [zs, c] of Object.entries(CORRIDOR[kind])) {
        if (d > s + c.aheadM) continue
        const z = Number(zs)
        const [tx, ty] = tileOf(lng, lat, z)
        const r = Math.ceil(c.radius)
        for (let dx = -r; dx <= r; dx++) {
          for (let dy = -r; dy <= r; dy++) {
            if (dx * dx + dy * dy > (c.radius + 0.5) ** 2) continue // a disc, not a square
            const key = `${kind}/${z}/${tx + dx}/${ty + dy}`
            if (missing.has(key)) continue
            // the bonus level comes after every other one: only if the network keeps up
            const prio = Math.abs(d - s) + (kind === 'sat' && z >= BONUS_ZOOM ? 1e6 : 0)
            if (!order.has(key) || order.get(key)! > prio) order.set(key, prio)
          }
        }
      }
    }
  }
  return [...order.entries()].sort((a, b) => a[1] - b[1]).map(([k]) => k)
}

/** Keep the cache to `keys` (drop the others) and queue the missing ones, nearest first. */
export function prefetch(keys: string[]): void {
  const keep = new Set(keys)
  for (const [k, buf] of cache) {
    if (!keep.has(k)) {
      cache.delete(k)
      tileStats.cachedBytes -= buf.byteLength
    }
  }
  tileStats.cachedTiles = cache.size
  queue = keys.filter((k) => !cache.has(k) && !inflight.has(k))
  pump()
}

function pump(): void {
  while (active < MAX_PARALLEL && queue.length) {
    const key = queue.shift()!
    const gen = generation
    active++
    download(key)
      .then((buf) => {
        if (gen !== generation || cache.has(key)) return
        cache.set(key, buf)
        tileStats.prefetched++
        tileStats.prefetchedBytes += buf.byteLength
        tileStats.cachedBytes += buf.byteLength
        tileStats.cachedTiles = cache.size
      })
      .catch(() => {}) // a missing tile is not fatal: MapLibre asks again if it needs it
      .finally(() => {
        active--
        pump()
      })
  }
}

export function clearTileCache(): void {
  generation++
  cache.clear()
  queue = []
  tileStats.cachedTiles = 0
  tileStats.cachedBytes = 0
}

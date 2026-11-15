import assert from 'node:assert/strict'
import { clearTileCache, loadTile, prefetch, tileStats, wantedTiles } from '../src/scenery/tiles'

// fake network: every request counted, answered after a few ms
const fetched = new Map<string, number>()
globalThis.fetch = (async (url: string | URL) => {
  const u = String(url)
  fetched.set(u, (fetched.get(u) ?? 0) + 1)
  await new Promise((r) => setTimeout(r, 3))
  return new Response(new Uint8Array(64))
}) as typeof fetch

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
async function settle(): Promise<void> {
  let last = -1
  while (tileStats.downloadedTiles !== last) {
    last = tileStats.downloadedTiles
    await sleep(40)
  }
}

// a straight 2 km route heading north from Annecy (IGN coverage)
const points = (d: number): [number, number] => [6.13, 45.9 + d / 111_000]

export const checks = {
  'no tile downloaded twice (prefetch and MapLibre asking at the same time)': async () => {
    clearTileCache()
    fetched.clear()
    const keys = wantedTiles(points, 0, 2000).slice(0, 120)
    prefetch(keys)
    // MapLibre asks for some of the same tiles while they are queued or downloading
    await Promise.all(keys.slice(0, 30).map((k) => loadTile({ url: `ht://${k}` } as never, new AbortController())))
    await settle()
    const twice = [...fetched.entries()].filter(([, n]) => n > 1)
    assert.equal(twice.length, 0, `downloaded twice: ${twice.slice(0, 3).map(([u]) => u).join(', ')}`)
    assert.equal(tileStats.cachedTiles, keys.length)
  },
  'moving on drops the tiles left behind': async () => {
    clearTileCache()
    prefetch(wantedTiles(points, 0, 2000).slice(0, 60))
    await settle()
    const ahead = wantedTiles(points, 1500, 3000).slice(0, 60)
    prefetch(ahead)
    await settle()
    assert.equal(tileStats.cachedTiles, ahead.length)
  },
  'clearing empties the cache, late downloads included': async () => {
    clearTileCache()
    prefetch(wantedTiles(points, 0, 2000).slice(0, 60))
    clearTileCache() // the view closes while downloads are in flight
    await settle()
    assert.equal(tileStats.cachedTiles, 0)
    assert.equal(tileStats.cachedBytes, 0)
  },
}

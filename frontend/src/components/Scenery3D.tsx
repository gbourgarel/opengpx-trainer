// 3D view of the route (terrain + satellite imagery) following the rider.
//
// Loaded on demand (React.lazy): MapLibre GL and its CSS land in a separate chunk, fetched only
// when this view is shown. The rider's position comes from the live telemetry (4 Hz) and is
// extrapolated between samples so the camera moves smoothly at the display frame rate.
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef } from 'react'
import type { RouteDetail, Telemetry } from '../api'
import { autoCamera, newCameraState, type Frame } from '../scenery/camera'
import { followPosition, pointAt, routeGeo, toLngLat } from '../scenery/route3d'
import { clearTileCache, DEM_MAX_ZOOM, DEM_URL, IMAGERY_MAX_ZOOM, IMAGERY_URL, loadTile, prefetch, tileStats, wantedTiles } from '../scenery/tiles'

/** Vertical field of view (deg): a wide angle shows the landscape around the road. */
const FOV = 65
/** Resolution of the 3D view on high-density screens (the overlays stay at full resolution). */
const MAX_PIXEL_RATIO = 1.5

let protocolAdded = false

export default function Scenery3D({ route, tel }: { route: RouteDetail; tel: Telemetry }) {
  const box = useRef<HTMLDivElement>(null)
  const live = useRef({ s: 0, v: 0, at: 0, known: false })

  // latest telemetry for the animation loop (no re-render of the map)
  const s = tel.route_position_m
  const speed = tel.state === 'running' ? (tel.speed_kmh ?? 0) / 3.6 : 0
  useEffect(() => {
    if (s == null) return
    live.current = { s, v: speed, at: performance.now(), known: true }
  }, [s, speed])

  // the ride is over: the prefetched tiles are no longer needed
  const over = !['ready', 'running', 'paused'].includes(tel.state)
  useEffect(() => {
    if (over) clearTileCache()
  }, [over])

  useEffect(() => {
    if (!box.current) return
    if (!protocolAdded) {
      maplibregl.addProtocol('ht', loadTile)
      protocolAdded = true
    }
    const g = routeGeo(route)
    // ?debug3d: counters on window.__scenery (fps, rider on screen, tiles); ?debug3d&imgz=18 caps
    // the imagery zoom (to compare levels)
    const params = new URLSearchParams(location.search)
    const debug = params.has('debug3d')
    const imageryMaxZoom = debug && params.get('imgz') ? Number(params.get('imgz')) : IMAGERY_MAX_ZOOM
    const stats = { frames: 0, riderOut: 0, riderNearEdge: 0, riderMinMarginPx: Infinity, worst: null as null | { s: number; x: number; y: number }, rider: { x: 0, y: 0 } }
    if (debug) Object.assign(window, { __tileStats: tileStats, __scenery: stats })
    const map = new maplibregl.Map({
      container: box.current,
      interactive: false,
      maxPitch: 85,
      // the attributions are shown by the immersive overlay (one line between its panels)
      attributionControl: false,
      // a pitched view shows many tiles at several zooms: the default cache (sized from the
      // viewport) dropped tiles still in view, which were then fetched again
      maxTileCacheSize: 3000,
      maxTileCacheZoomLevels: 10,
      // drawn at 1.5x at most on Retina screens: hardly distinguishable from 2x (the imagery is
      // the limit, not the pixels) and +15 % frame rate on the user's Mac (user's choice)
      pixelRatio: Math.min(window.devicePixelRatio, MAX_PIXEL_RATIO),
      center: [g.lon0, g.lat0],
      zoom: 13,
      style: {
        version: 8,
        sources: {
          imagery: { type: 'raster', tiles: [IMAGERY_URL], tileSize: 256, maxzoom: imageryMaxZoom },
          dem: { type: 'raster-dem', tiles: [DEM_URL], tileSize: 256, maxzoom: DEM_MAX_ZOOM, encoding: 'terrarium' },
          route: { type: 'geojson', data: { type: 'LineString', coordinates: route.latlon.map(([lat, lon]) => [lon, lat]) } },
          rider: { type: 'geojson', data: { type: 'Point', coordinates: [g.lon0, g.lat0] } },
        },
        layers: [
          { id: 'imagery', type: 'raster', source: 'imagery' },
          { id: 'route', type: 'line', source: 'route', paint: { 'line-color': '#ff6a00', 'line-width': 4, 'line-opacity': 0.85 } },
          {
            id: 'rider',
            type: 'circle',
            source: 'rider',
            // fixed size on screen (it would otherwise grow when close to the camera)
            paint: { 'circle-radius': 7, 'circle-color': '#fff', 'circle-stroke-color': '#ff3d00', 'circle-stroke-width': 3, 'circle-pitch-scale': 'viewport' },
          },
        ],
        terrain: { source: 'dem', exaggeration: 1 },
        sky: { 'sky-color': '#7fb4e6', 'horizon-color': '#dce9f5', 'fog-color': '#dce9f5', 'sky-horizon-blend': 0.6, 'horizon-fog-blend': 0.6, 'fog-ground-blend': 0.85 },
      },
    })
    let raf = 0
    let last: number | null = null
    let shown: number | null = null
    let prefetchedAt = -1e9
    const lngLatAt = (d: number) => {
      const [x, y] = pointAt(g, d)
      return toLngLat(g, x, y)
    }
    const cam = newCameraState()
    // Ground height for the camera (many points per frame: line of sight to the rider). Not
    // map.queryTerrainElevation: it recomputes the tiles covering the view on every call only to
    // pick the DEM zoom (~40 % of the main thread in a profile, the frame rate's bottleneck). The
    // finest DEM level is asked directly; MapLibre falls back to the loaded parent tile.
    const ground = (lng: number, lat: number) =>
      map.terrain ? map.terrain.getElevationForLngLatZoom(new maplibregl.LngLat(lng, lat), DEM_MAX_ZOOM) : null

    const frame = (t: number) => {
      const dt = last == null ? 0 : Math.min((t - last) / 1000, 0.25)
      last = t
      const l = live.current
      if (l.known) {
        shown = followPosition(shown, { s: l.s, v: l.v, ageS: (performance.now() - l.at) / 1000 }, dt, g.total)
        if (Math.abs(shown - prefetchedAt) >= 25) {
          // the next kilometre of tiles, refreshed every 25 m ridden
          prefetchedAt = shown
          prefetch(wantedTiles(lngLatAt, shown, g.total))
        }
        const c = map.getCanvas()
        // the rider stays clear of the immersive view's panels: above the bottom ones (~28 % of
        // the height) and between the side ones (~310 px wide on the right) — with 14 % / 60 px
        // the rider went under the route block in the first town turns
        const frame: Frame = {
          width: c.clientWidth,
          height: c.clientHeight,
          fovDeg: FOV,
          bottomMarginPx: 0.3 * c.clientHeight,
          sideMarginPx: Math.min(320, 0.22 * c.clientWidth),
        }
        const { pose } = autoCamera(g, shown, l.v, cam, dt, ground, frame, map.transform.cameraToCenterDistance)
        map.jumpTo(pose)
        const [x, y] = pointAt(g, shown)
        const riderLL = toLngLat(g, x, y)
        ;(map.getSource('rider') as maplibregl.GeoJSONSource | undefined)?.setData({ type: 'Point', coordinates: riderLL })
        if (debug) {
          // where the rider really is on screen (MapLibre's projection, terrain included)
          stats.frames++
          const p = map.project(riderLL)
          stats.rider = { x: p.x, y: p.y }
          const margin = Math.min(p.x, p.y, frame.width - p.x, frame.height - p.y)
          if (margin < 0) stats.riderOut++
          else if (margin < 40) stats.riderNearEdge++
          if (margin < stats.riderMinMarginPx) {
            stats.riderMinMarginPx = margin
            stats.worst = { s: Math.round(shown), x: Math.round(p.x), y: Math.round(p.y) }
          }
        }
      }
      raf = requestAnimationFrame(frame)
    }
    // a tile missing at the finest level is expected (the coarser one is shown): not an error
    map.on('error', (e) => {
      if ((e.error as Error | undefined)?.name === 'NoTile' || String(e.error?.message).startsWith('no tile')) return
      console.error(e.error)
    })
    map.on('load', () => {
      map.setVerticalFieldOfView(FOV)
      raf = requestAnimationFrame(frame)
    })
    return () => {
      cancelAnimationFrame(raf)
      map.remove()
      clearTileCache() // view closed: nothing kept
    }
  }, [route])

  return <div ref={box} className="scenery3d" />
}

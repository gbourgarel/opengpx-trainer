// 3D view of the route (terrain + satellite imagery) following the rider.
//
// Loaded on demand (React.lazy): MapLibre GL and its CSS land in a separate chunk, fetched only
// when this view is shown. The rider's position comes from the live telemetry (4 Hz) and is
// extrapolated between samples so the camera moves smoothly at the display frame rate.
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef } from 'react'
import type { RouteDetail, Telemetry } from '../api'
import { chaseCamera, newCameraState } from '../scenery/camera'
import { followPosition, pointAt, routeGeo, toLngLat } from '../scenery/route3d'
import { ATTRIBUTION, DEM_MAX_ZOOM, DEM_URL, IMAGERY_MAX_ZOOM, IMAGERY_URL, loadTile } from '../scenery/tiles'

/** Vertical field of view (deg): a wide angle shows the landscape around the road. */
const FOV = 65

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

  useEffect(() => {
    if (!box.current) return
    if (!protocolAdded) {
      maplibregl.addProtocol('ht', loadTile)
      protocolAdded = true
    }
    const g = routeGeo(route)
    const map = new maplibregl.Map({
      container: box.current,
      interactive: false,
      maxPitch: 85,
      attributionControl: { compact: true },
      // a pitched view shows many tiles at several zooms: the default cache (sized from the
      // viewport) dropped tiles still in view, which were then fetched again
      maxTileCacheSize: 3000,
      maxTileCacheZoomLevels: 10,
      center: [g.lon0, g.lat0],
      zoom: 13,
      style: {
        version: 8,
        sources: {
          imagery: { type: 'raster', tiles: [IMAGERY_URL], tileSize: 256, maxzoom: IMAGERY_MAX_ZOOM, attribution: ATTRIBUTION },
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
    const cam = newCameraState()
    const ground = (lng: number, lat: number) => map.queryTerrainElevation([lng, lat])

    const frame = (t: number) => {
      const dt = last == null ? 0 : Math.min((t - last) / 1000, 0.25)
      last = t
      const l = live.current
      if (l.known) {
        shown = followPosition(shown, { s: l.s, v: l.v, ageS: (performance.now() - l.at) / 1000 }, dt, g.total)
        const pose = chaseCamera(g, shown, cam, dt, ground, map.transform.cameraToCenterDistance)
        map.jumpTo(pose)
        const [x, y] = pointAt(g, shown)
        ;(map.getSource('rider') as maplibregl.GeoJSONSource | undefined)?.setData({ type: 'Point', coordinates: toLngLat(g, x, y) })
      }
      raf = requestAnimationFrame(frame)
    }
    map.on('load', () => {
      map.setVerticalFieldOfView(FOV)
      raf = requestAnimationFrame(frame)
    })
    return () => {
      cancelAnimationFrame(raf)
      map.remove()
    }
  }, [route])

  return <div ref={box} className="scenery3d" />
}

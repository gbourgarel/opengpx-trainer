import { useEffect } from 'react'
import { CircleMarker, MapContainer, Polyline, TileLayer, useMap, useMapEvents } from 'react-leaflet'
import type { LatLngBoundsExpression, LatLngExpression } from 'leaflet'
import 'leaflet/dist/leaflet.css'

function FitBounds({ bounds }: { bounds: LatLngBoundsExpression }) {
  const map = useMap()
  useEffect(() => {
    // no animation: leaving the page mid-zoom made Leaflet throw "_leaflet_pos" of undefined
    map.fitBounds(bounds, { padding: [20, 20], animate: false })
  }, [map, bounds])
  return null
}

function Follow({ pos, follow }: { pos?: LatLngExpression; follow: boolean }) {
  const map = useMap()
  useEffect(() => {
    if (follow && pos) map.panTo(pos, { animate: true, duration: 0.25 })
  }, [map, pos, follow])
  return null
}

function Pick({ onPick }: { onPick: (at: [number, number]) => void }) {
  useMapEvents({ click: (e) => onPick([e.latlng.lat, e.latlng.lng]) })
  return null
}

export function RouteMap({
  latlon,
  position,
  follow = false,
  done,
  height = 320,
  start,
  onPick,
}: {
  latlon: [number, number][]
  position?: [number, number]
  follow?: boolean
  done?: number // index into latlon reached so far
  height?: number | string // px, or e.g. "100%" to fill a sized parent
  /** index of the start point of a ride started part-way: the part before it is greyed */
  start?: number
  /** click on the map (to choose a start point) */
  onPick?: (at: [number, number]) => void
}) {
  if (!latlon.length) return null
  const from = start ?? 0
  return (
    <MapContainer style={{ height }} className="map" center={latlon[0]} zoom={13} scrollWheelZoom>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <Polyline positions={latlon} pathOptions={{ color: '#4f7cff', weight: 4, opacity: 0.8 }} />
      {from > 0 && <Polyline positions={latlon.slice(0, from + 1)} pathOptions={{ color: '#8a93a6', weight: 4, opacity: 0.9 }} />}
      {done != null && done > from && (
        <Polyline positions={latlon.slice(from, done + 1)} pathOptions={{ color: '#ff6b35', weight: 5 }} />
      )}
      {from > 0 && !position && (
        <CircleMarker center={latlon[from]} radius={7} pathOptions={{ color: '#fff', weight: 3, fillColor: '#4f7cff', fillOpacity: 1 }} />
      )}
      {onPick && <Pick onPick={onPick} />}
      {position && (
        <CircleMarker center={position} radius={8} pathOptions={{ color: '#fff', weight: 3, fillColor: '#ff6b35', fillOpacity: 1 }} />
      )}
      <FitBounds bounds={latlon} />
      <Follow pos={position} follow={follow} />
    </MapContainer>
  )
}

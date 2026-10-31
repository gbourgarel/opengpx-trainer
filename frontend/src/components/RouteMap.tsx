import { useEffect } from 'react'
import { CircleMarker, MapContainer, Polyline, TileLayer, useMap } from 'react-leaflet'
import type { LatLngBoundsExpression, LatLngExpression } from 'leaflet'
import 'leaflet/dist/leaflet.css'

function FitBounds({ bounds }: { bounds: LatLngBoundsExpression }) {
  const map = useMap()
  useEffect(() => {
    map.fitBounds(bounds, { padding: [20, 20] })
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

export function RouteMap({
  latlon,
  position,
  follow = false,
  done,
  height = 320,
}: {
  latlon: [number, number][]
  position?: [number, number]
  follow?: boolean
  done?: number // index into latlon reached so far
  height?: number
}) {
  if (!latlon.length) return null
  return (
    <MapContainer style={{ height }} className="map" center={latlon[0]} zoom={13} scrollWheelZoom>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <Polyline positions={latlon} pathOptions={{ color: '#4f7cff', weight: 4, opacity: 0.8 }} />
      {done != null && done > 0 && (
        <Polyline positions={latlon.slice(0, done + 1)} pathOptions={{ color: '#ff6b35', weight: 5 }} />
      )}
      {position && (
        <CircleMarker center={position} radius={8} pathOptions={{ color: '#fff', weight: 3, fillColor: '#ff6b35', fillOpacity: 1 }} />
      )}
      <FitBounds bounds={latlon} />
      <Follow pos={position} follow={follow} />
    </MapContainer>
  )
}

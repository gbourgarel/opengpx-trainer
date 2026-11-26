import { createContext } from 'react'

/** The profile's map tile settings, provided by App to every RouteMap. */
export const MapTilesContext = createContext({ url: '', attribution: '' })

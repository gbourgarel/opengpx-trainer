/** Wind helpers: compass names and the wind remembered for the next GPX ride. */

const COMPASS_POINTS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']

/** 16-point compass name of a direction in degrees (0 = north, clockwise). */
export function compassName(deg: number): string {
  return COMPASS_POINTS[Math.round((((deg % 360) + 360) % 360) / 22.5) % 16]
}

export interface WindSetting {
  kmh: number
  fromDeg: number // direction the wind blows FROM (meteorological convention)
}

const STORAGE_KEY = 'hometrainer.wind'

/** The last wind used (per browser), to start the next ride with it. */
export function loadWind(): WindSetting {
  try {
    const w = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '') as WindSetting
    if (Number.isFinite(w.kmh) && Number.isFinite(w.fromDeg)) return w
  } catch {
    /* none stored / private mode */
  }
  return { kmh: 0, fromDeg: 0 }
}

export function saveWind(w: WindSetting) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(w))
  } catch {
    /* not remembered */
  }
}

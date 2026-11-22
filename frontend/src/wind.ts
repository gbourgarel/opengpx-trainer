/** Conditions of a GPX ride: compass names, and the wind and air remembered for the next
 * ride (per browser). */

import { getSetting, setSetting } from './localSettings'

const COMPASS_POINTS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']

/** 16-point compass name of a direction in degrees (0 = north, clockwise). */
export function compassName(deg: number): string {
  return COMPASS_POINTS[Math.round((((deg % 360) + 360) % 360) / 22.5) % 16]
}

export interface WindSetting {
  kmh: number
  fromDeg: number // direction the wind blows FROM (meteorological convention)
}

const WIND_SETTING = 'wind'

/** The last wind used (per browser), to start the next ride with it. */
export function loadWind(): WindSetting {
  try {
    const w = JSON.parse(getSetting(WIND_SETTING) ?? '') as WindSetting
    if (Number.isFinite(w.kmh) && Number.isFinite(w.fromDeg)) return w
  } catch {
    /* none stored / private mode */
  }
  return { kmh: 0, fromDeg: 0 }
}

export function saveWind(w: WindSetting) {
  try {
    setSetting(WIND_SETTING, JSON.stringify(w))
  } catch {
    /* not remembered */
  }
}

/** Air of a GPX ride (density), chosen with the wind and remembered the same way. */
export interface AirSetting {
  temperature_c: number
  relative_humidity: number // 0-1
}

const AIR_SETTING = 'air'
// first use: the Profile's former default (the air was a profile setting before 2026-11-15)
const DEFAULT_AIR: AirSetting = { temperature_c: 20, relative_humidity: 0.5 }

export function loadAir(): AirSetting {
  try {
    const a = JSON.parse(getSetting(AIR_SETTING) ?? '') as AirSetting
    if (Number.isFinite(a.temperature_c) && Number.isFinite(a.relative_humidity)) return a
  } catch {
    /* none stored / private mode */
  }
  return DEFAULT_AIR
}

export function saveAir(a: AirSetting) {
  try {
    setSetting(AIR_SETTING, JSON.stringify(a))
  } catch {
    /* not remembered */
  }
}

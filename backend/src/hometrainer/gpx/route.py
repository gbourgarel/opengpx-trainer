"""GPX route processing.

* Distances are horizontal (map) distances computed with the haversine formula.
* The track is resampled on a uniform distance grid so grade can be derived robustly.
* GPS/barometric elevation is noisy, and differentiating noise gives absurd grades, so elevation
  is smoothed with a Gaussian kernel in the *distance* domain before computing the grade.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import gpxpy
import numpy as np

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


def gaussian_smooth(values: np.ndarray, step_m: float, sigma_m: float) -> np.ndarray:
    if sigma_m <= 0 or len(values) < 3:
        return values.copy()
    half = min(int(math.ceil(3 * sigma_m / step_m)), len(values) - 1)
    x = np.arange(-half, half + 1) * step_m
    k = np.exp(-0.5 * (x / sigma_m) ** 2)
    k /= k.sum()
    # odd reflection preserves the end slopes (edge padding would flatten the grade at the ends)
    padded = np.pad(values, half, mode="reflect", reflect_type="odd")
    return np.convolve(padded, k, mode="valid")


@dataclass(frozen=True)
class RoutePoint:
    distance_m: float
    lat: float
    lon: float
    altitude_m: float
    grade: float  # rise/run
    heading_deg: float


class Route:
    def __init__(
        self,
        name: str,
        lat: np.ndarray,
        lon: np.ndarray,
        ele: np.ndarray,
        step_m: float = 5.0,
        smoothing_sigma_m: float = 25.0,
        max_abs_grade: float = 0.30,
    ):
        if len(lat) < 2:
            raise ValueError("Route needs at least two points")
        self.name = name
        seg = haversine_m(lat[:-1], lon[:-1], lat[1:], lon[1:])
        keep = np.concatenate([[True], seg > 0.2])  # drop duplicated points
        lat, lon, ele = lat[keep], lon[keep], ele[keep]
        cum = np.concatenate([[0.0], np.cumsum(haversine_m(lat[:-1], lon[:-1], lat[1:], lon[1:]))])
        self.total_distance_m = float(cum[-1])
        # exactly uniform grid (step slightly adjusted) so smoothing & gradient are consistent
        n = max(2, int(math.ceil(self.total_distance_m / step_m)))
        self.d = np.linspace(0.0, self.total_distance_m, n + 1)
        self.step_m = step_m = float(self.d[1] - self.d[0])
        self.lat = np.interp(self.d, cum, lat)
        self.lon = np.interp(self.d, cum, lon)
        self.raw_ele = np.interp(self.d, cum, ele)
        self.ele = gaussian_smooth(self.raw_ele, step_m, smoothing_sigma_m)
        self.grade = np.clip(np.gradient(self.ele, self.d), -max_abs_grade, max_abs_grade)
        # cumulative positive elevation gain along the route (same smoothed profile as ascent_m)
        rises = np.clip(np.diff(self.ele), 0.0, None)
        self.cum_gain = np.concatenate([[0.0], np.cumsum(rises)])

        dlon = np.radians(np.diff(self.lon))
        la1, la2 = np.radians(self.lat[:-1]), np.radians(self.lat[1:])
        y = np.sin(dlon) * np.cos(la2)
        x = np.cos(la1) * np.sin(la2) - np.sin(la1) * np.cos(la2) * np.cos(dlon)
        hdg = (np.degrees(np.arctan2(y, x)) + 360) % 360
        self.heading = np.concatenate([hdg, hdg[-1:]])

    # --- construction ----------------------------------------------------------------------
    @classmethod
    def from_gpx(cls, text: str, **kwargs) -> Route:
        gpx = gpxpy.parse(text)
        pts = [p for t in gpx.tracks for s in t.segments for p in s.points]
        if not pts:
            pts = [p for r in gpx.routes for p in r.points]
        if not pts:
            raise ValueError("GPX contains no track or route points")
        name = gpx.name or (gpx.tracks[0].name if gpx.tracks else None) or "Route"
        ele = np.array([p.elevation if p.elevation is not None else np.nan for p in pts], float)
        if np.all(np.isnan(ele)):
            ele[:] = 0.0  # TODO: fetch elevation from a DEM when the GPX has none
        elif np.any(np.isnan(ele)):
            idx = np.arange(len(ele))
            ok = ~np.isnan(ele)
            ele = np.interp(idx, idx[ok], ele[ok])
        lat = np.array([p.latitude for p in pts], float)
        lon = np.array([p.longitude for p in pts], float)
        return cls(name, lat, lon, ele, **kwargs)

    # --- queries -------------------------------------------------------------------------
    def clamp(self, distance_m: float) -> float:
        return min(max(distance_m, 0.0), self.total_distance_m)

    def grade_at(self, distance_m: float) -> float:
        return float(np.interp(self.clamp(distance_m), self.d, self.grade))

    def altitude_at(self, distance_m: float) -> float:
        return float(np.interp(self.clamp(distance_m), self.d, self.ele))

    def grade_and_altitude(self, distance_m: float) -> tuple[float, float]:
        d = self.clamp(distance_m)
        return float(np.interp(d, self.d, self.grade)), float(np.interp(d, self.d, self.ele))

    def gain_between(self, start_m: float, end_m: float) -> float:
        """Positive elevation gain (m) between two positions on the route."""
        a, b = self.clamp(start_m), self.clamp(end_m)
        if b <= a:
            return 0.0
        return float(np.interp(b, self.d, self.cum_gain) - np.interp(a, self.d, self.cum_gain))

    def mean_grade(self, start_m: float, length_m: float) -> float:
        """Average grade over [start, start + length] (elevation difference / distance)."""
        a = self.clamp(start_m)
        b = self.clamp(start_m + length_m)
        if b - a < 1.0:
            return self.grade_at(a)
        return (self.altitude_at(b) - self.altitude_at(a)) / (b - a)

    def point_at(self, distance_m: float) -> RoutePoint:
        d = self.clamp(distance_m)
        i = min(int(d // self.step_m), len(self.d) - 1)
        return RoutePoint(
            distance_m=d,
            lat=float(np.interp(d, self.d, self.lat)),
            lon=float(np.interp(d, self.d, self.lon)),
            altitude_m=float(np.interp(d, self.d, self.ele)),
            grade=float(np.interp(d, self.d, self.grade)),
            heading_deg=float(self.heading[i]),
        )

    # --- summaries -----------------------------------------------------------------------
    @property
    def ascent_m(self) -> float:
        diff = np.diff(self.ele)
        return float(diff[diff > 0].sum())

    @property
    def descent_m(self) -> float:
        diff = np.diff(self.ele)
        return float(-diff[diff < 0].sum())

    def summary(self) -> dict:
        return {
            "name": self.name,
            "distance_m": round(self.total_distance_m, 1),
            "ascent_m": round(self.ascent_m, 1),
            "descent_m": round(self.descent_m, 1) + 0.0,
            "max_grade": round(float(self.grade.max()), 4),
            "min_grade": round(float(self.grade.min()), 4),
            "min_altitude_m": round(float(self.ele.min()), 1),
            "max_altitude_m": round(float(self.ele.max()), 1),
        }

    def geometry(self, max_points: int = 2000) -> dict:
        """Decimated polyline + elevation profile for the UI."""
        stride = max(1, len(self.d) // max_points)
        idx = np.unique(np.concatenate([np.arange(0, len(self.d), stride), [len(self.d) - 1]]))
        return {
            "latlon": np.column_stack([self.lat[idx], self.lon[idx]]).round(6).tolist(),
            "profile_distance_m": self.d[idx].round(1).tolist(),
            "altitude_m": self.ele[idx].round(1).tolist(),
            "grade": self.grade[idx].round(4).tolist(),
        }

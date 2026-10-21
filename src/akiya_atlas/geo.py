"""Spherical distances in km. Coordinates are always (longitude, latitude)."""

from __future__ import annotations

import math
from collections.abc import Iterable

EARTH_KM = 6371.0088
Point = tuple[float, float]


def valid_point(point: Point) -> bool:
    lon, lat = point
    return math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90


def distance_km(a: Point, b: Point) -> float:
    """Haversine great-circle distance; stable at zero and at antipodes."""
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2
    h += math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(min(1, max(0, h))))


def _bearing(a: Point, b: Point) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    return math.atan2(
        math.sin(lon2 - lon1) * math.cos(lat2),
        math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1),
    )


def segment_distance_km(point: Point, a: Point, b: Point) -> float:
    """Distance to the minor great-circle arc, including both endpoints."""
    length = distance_km(a, b) / EARTH_KM
    if length < 1e-12:
        return distance_km(point, a)
    ap = distance_km(a, point) / EARTH_KM
    angle = _bearing(a, point) - _bearing(a, b)
    along = math.atan2(math.sin(ap) * math.cos(angle), math.cos(ap))
    if along < 0 or along > length:
        return min(distance_km(point, a), distance_km(point, b))
    cross = math.sin(ap) * math.sin(angle)
    return abs(math.asin(min(1, max(-1, cross)))) * EARTH_KM


def coast_distance_km(point: Point, lines: Iterable[list[Point]]) -> float:
    distances = (
        segment_distance_km(point, a, b)
        for line in lines
        for a, b in zip(line, line[1:], strict=False)
    )
    return min(distances)  # An empty coastline is an input error, never "0 km".


def estimated_drive_minutes(distance: float) -> int:
    """1.4 road/air ratio, 50 km/h and 15 min access allowance; NOT a route."""
    if not math.isfinite(distance) or distance < 0:
        raise ValueError("distance must be finite and nonnegative")
    return math.ceil(distance * 1.4 / 50 * 60 + 15)

"""Length and area measurement for lon/lat geometry, standard library only.

Like geometry.py, this avoids shapely/pyproj so the repo stays clone-and-run.
Chicago is small enough that an equirectangular projection about the local
latitude gives areas and lengths well within the accuracy this metric needs.
"""

from __future__ import annotations

import math
from typing import Any

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def line_length_km(coords: list[list[float]]) -> float:
    return sum(
        haversine_km(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
        for i in range(len(coords) - 1)
    )


def _ring_area_km2(ring: list[list[float]], lat0_rad: float) -> float:
    """Shoelace area of a ring projected equirectangularly about lat0."""
    if len(ring) < 3:
        return 0.0
    cos_lat0 = math.cos(lat0_rad)
    pts = [
        (math.radians(lng) * EARTH_RADIUS_KM * cos_lat0, math.radians(lat) * EARTH_RADIUS_KM)
        for lng, lat in ring
    ]
    total = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _polygon_area_km2(polygon: list[list[list[float]]], lat0_rad: float) -> float:
    if not polygon:
        return 0.0
    area = _ring_area_km2(polygon[0], lat0_rad)
    for hole in polygon[1:]:
        area -= _ring_area_km2(hole, lat0_rad)
    return max(0.0, area)


def geometry_area_km2(geometry: dict[str, Any]) -> float:
    geom_type = geometry.get("type")
    coords = geometry.get("coordinates") or []
    lats: list[float] = []

    def collect(points):
        for lng, lat in points:
            lats.append(lat)

    if geom_type == "Polygon":
        for ring in coords:
            collect(ring)
    elif geom_type == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                collect(ring)
    else:
        return 0.0
    lat0_rad = math.radians(sum(lats) / len(lats)) if lats else 0.0

    if geom_type == "Polygon":
        return _polygon_area_km2(coords, lat0_rad)
    return sum(_polygon_area_km2(poly, lat0_rad) for poly in coords)

"""Dependency-free point-in-polygon helpers for assigning sites to wards.

Chicago ward boundaries are simple lon/lat polygons, so a ray-casting test is
plenty accurate here and lets the repo run anywhere with just the standard
library. We deliberately avoid pulling in shapely/geopandas so a casual reader
can clone, run, and audit the whole pipeline without a geospatial toolchain.
"""

from __future__ import annotations

from typing import Any

Ring = list[list[float]]


def _point_in_ring(lng: float, lat: float, ring: Ring) -> bool:
    """Standard even-odd ray-casting test for a single linear ring."""
    inside = False
    count = len(ring)
    j = count - 1
    for i in range(count):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        intersects = (yi > lat) != (yj > lat)
        if intersects:
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lng < x_cross:
                inside = not inside
        j = i
    return inside


def _point_in_polygon(lng: float, lat: float, polygon: list[Ring]) -> bool:
    """A polygon is an exterior ring followed by zero or more holes."""
    if not polygon:
        return False
    if not _point_in_ring(lng, lat, polygon[0]):
        return False
    for hole in polygon[1:]:
        if _point_in_ring(lng, lat, hole):
            return False
    return True


def point_in_geometry(lng: float, lat: float, geometry: dict[str, Any]) -> bool:
    geom_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geom_type == "Polygon":
        return _point_in_polygon(lng, lat, coordinates)
    if geom_type == "MultiPolygon":
        return any(_point_in_polygon(lng, lat, polygon) for polygon in coordinates)
    return False


def feature_bounds(features: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    """Return (min_lat, min_lng, max_lat, max_lng) across all features."""
    min_lat = min_lng = float("inf")
    max_lat = max_lng = float("-inf")
    for feature in features:
        for lng, lat in _iter_coords(feature.get("geometry") or {}):
            min_lat, max_lat = min(min_lat, lat), max(max_lat, lat)
            min_lng, max_lng = min(min_lng, lng), max(max_lng, lng)
    if min_lat == float("inf"):
        raise ValueError("No coordinates found in features")
    return min_lat, min_lng, max_lat, max_lng


def _iter_coords(geometry: dict[str, Any]):
    geom_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geom_type == "Polygon":
        for ring in coordinates:
            yield from ring
    elif geom_type == "MultiPolygon":
        for polygon in coordinates:
            for ring in polygon:
                yield from ring

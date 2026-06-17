"""Load Chicago ward / community-area / ZIP boundaries and assign points to them.

Each geography is a GeoJSON of polygons bundled under data/reference/. A
``GeographyIndex`` wraps one of them and answers "which area contains this
point?" plus exposes each area's land area in km2 (for density metrics). All
three share the same point-in-polygon code from geometry.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .geometry import feature_bounds, point_in_geometry
from .measure import geometry_area_km2

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_DIR = REPO_ROOT / "data" / "reference"


@dataclass(frozen=True)
class GeographySpec:
    key: str            # "ward" | "community_area" | "zip"
    filename: str
    id_field: str
    name_field: str | None


GEOGRAPHIES: tuple[GeographySpec, ...] = (
    GeographySpec("ward", "ward_boundaries.geojson", "ward_id", "display_name"),
    GeographySpec("community_area", "community_areas.geojson", "community_area_id", "display_name"),
    GeographySpec("zip", "zip_boundaries.geojson", "zip", None),
)


@dataclass
class Area:
    area_id: str
    display_name: str
    area_km2: float


class GeographyIndex:
    def __init__(self, spec: GeographySpec, geojson: dict[str, Any]):
        self.spec = spec
        self.features = [
            feature
            for feature in geojson.get("features", [])
            if feature.get("geometry") and feature.get("properties", {}).get(spec.id_field)
        ]
        if not self.features:
            raise ValueError(f"{spec.key} boundaries contain no usable features")
        self.bounds = feature_bounds(self.features)
        self._areas = {
            self._id(feature): Area(
                area_id=self._id(feature),
                display_name=self._name(feature),
                area_km2=round(geometry_area_km2(feature["geometry"]), 4),
            )
            for feature in self.features
        }

    def _id(self, feature: dict[str, Any]) -> str:
        return str(feature["properties"][self.spec.id_field])

    def _name(self, feature: dict[str, Any]) -> str:
        if self.spec.name_field:
            return str(feature["properties"].get(self.spec.name_field) or self._id(feature))
        return self._id(feature)

    @classmethod
    def load(cls, spec: GeographySpec, reference_dir: Path = REFERENCE_DIR) -> "GeographyIndex":
        with open(reference_dir / spec.filename, encoding="utf-8") as handle:
            return cls(spec, json.load(handle))

    def areas(self) -> list[Area]:
        return [self._areas[area_id] for area_id in sorted(self._areas)]

    def area(self, area_id: str) -> Area | None:
        return self._areas.get(area_id)

    def assign(self, lat: float, lng: float) -> str | None:
        min_lat, min_lng, max_lat, max_lng = self.bounds
        if not (min_lat <= lat <= max_lat and min_lng <= lng <= max_lng):
            return None
        for feature in self.features:
            if point_in_geometry(lng, lat, feature["geometry"]):
                return self._id(feature)
        return None


def load_all(reference_dir: Path = REFERENCE_DIR) -> dict[str, GeographyIndex]:
    return {spec.key: GeographyIndex.load(spec, reference_dir) for spec in GEOGRAPHIES}

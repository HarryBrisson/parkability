"""parkability pipeline: build per-geography parking metrics for Chicago.

Phase 1 metrics:
  * offstreet_parking_sites_per_sqkm  -- OSM off-street parking supply density
                                         (ward / community area / zip)
  * permit_zone_block_faces_per_sqkm  -- residential permit-zone density, a clean
                                         scarcity signal (ward only for now; the
                                         source carries ward but no geometry)

Outputs per geography to data/processed/<geo>_parking_summary.{json,csv} plus a
metadata.json capturing provenance, caveats, and which metric is available where.
The ward summary is what ward-wise-explorer (Penlight) ingests.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .geographies import GeographyIndex, GeographySpec, load_all
from .sources import car_ownership, complaints_311, parking_osm, permit_zones

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

SOURCE_LABEL = "parkability"
SOURCE_URL = "https://github.com/HarryBrisson/parkability"

# Metrics available per geography (permit zones are ward-only until geocoded).
PARKING_METRIC = "offstreet_parking_sites_per_sqkm"
PERMIT_METRIC = "permit_zone_block_faces_per_sqkm"
COMPLAINTS_METRIC = "parking_311_complaints_per_sqkm"
COMPLAINTS_SHARE_METRIC = "parking_311_share_of_local_complaints_pct"
VEHICLES_METRIC = "vehicles_per_household"


def _round(value: float | None, places: int = 2) -> float | None:
    return None if value is None else round(value, places)


def assign_parking(payload: dict[str, Any], indexes: dict[str, GeographyIndex]):
    """Assign each OSM parking site to every geography. Returns per-geo accumulators."""
    accum = {
        key: defaultdict(lambda: {"site_count": 0, "capacity": 0, "capacity_known": 0})
        for key in indexes
    }
    audit = Counter()
    for _osm_type, _osm_id, lat, lng, capacity, _ptype in parking_osm.iter_parking_sites(payload):
        audit["parking_sites_total"] += 1
        for key, index in indexes.items():
            area_id = index.assign(lat, lng)
            if area_id is None:
                continue
            bucket = accum[key][area_id]
            bucket["site_count"] += 1
            if capacity is not None:
                bucket["capacity"] += capacity
                bucket["capacity_known"] += 1
    return accum, dict(audit)


def assign_tracts(records: list[dict[str, Any]], indexes: dict[str, GeographyIndex]):
    """Sum tract car-ownership/population into each geography by tract centroid."""
    accum = {
        key: defaultdict(lambda: {"vehicles": 0, "households": 0, "population": 0})
        for key in indexes
    }
    audit = Counter()
    for record in records:
        audit["tracts_total"] += 1
        for key, index in indexes.items():
            area_id = index.assign(record["lat"], record["lng"])
            if area_id is None:
                continue
            bucket = accum[key][area_id]
            bucket["vehicles"] += record["vehicles"]
            bucket["households"] += record["households"]
            bucket["population"] += record["population"]
    return accum, dict(audit)


def assign_permit_zones(rows: list[dict[str, Any]], ward_index: GeographyIndex):
    by_ward = defaultdict(lambda: {"block_faces": 0, "buffer": 0, "zones": set()})
    audit = Counter()
    ward_ids = {area.area_id for area in ward_index.areas()}
    for ward_id, zone, is_buffer in permit_zones.iter_active_block_faces(rows):
        audit["permit_block_faces_assigned"] += 1
        if ward_id not in ward_ids:
            audit["permit_block_faces_unknown_ward"] += 1
            continue
        bucket = by_ward[ward_id]
        bucket["block_faces"] += 1
        if is_buffer:
            bucket["buffer"] += 1
        if zone:
            bucket["zones"].add(zone)
    return by_ward, dict(audit)


def build_summary(
    spec: GeographySpec,
    index: GeographyIndex,
    parking_accum: dict[str, dict[str, int]],
    complaints_counts: dict[str, dict[str, int]],
    tracts_accum: dict[str, dict[str, int]],
    permit_by_ward: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for area in index.areas():
        bucket = parking_accum.get(area.area_id, {"site_count": 0, "capacity": 0, "capacity_known": 0})
        complaints = complaints_counts.get(
            area.area_id, {"abandoned": 0, "bike_lane": 0, "parking_total": 0, "local_total": 0}
        )
        demand = tracts_accum.get(area.area_id, {"vehicles": 0, "households": 0, "population": 0})
        area_km2 = area.area_km2
        parking_density = bucket["site_count"] / area_km2 if area_km2 > 0 else None
        parking_total = complaints["parking_total"]
        local_total = complaints["local_total"]
        complaints_density = parking_total / area_km2 if area_km2 > 0 else None
        complaints_share = (parking_total / local_total * 100) if local_total > 0 else None
        row: dict[str, Any] = {
            "area_type": spec.key,
            "area_id": area.area_id,
            "display_name": area.display_name,
            "area_km2": area_km2,
            "offstreet_parking_site_count": bucket["site_count"],
            "offstreet_parking_capacity_spaces": bucket["capacity"],
            "offstreet_parking_capacity_known_sites": bucket["capacity_known"],
            PARKING_METRIC: _round(parking_density),
            "parking_311_complaint_count": parking_total,
            "parking_311_abandoned_vehicle_count": complaints["abandoned"],
            "parking_311_bike_lane_count": complaints["bike_lane"],
            "local_311_complaint_count": local_total,
            COMPLAINTS_METRIC: _round(complaints_density),
            COMPLAINTS_SHARE_METRIC: _round(complaints_share, 3),
            "population": demand["population"],
            "households": demand["households"],
            "vehicles": demand["vehicles"],
            VEHICLES_METRIC: _round(demand["vehicles"] / demand["households"], 3) if demand["households"] > 0 else None,
        }
        if permit_by_ward is not None:
            permit = permit_by_ward.get(area.area_id)
            faces = permit["block_faces"] if permit else 0
            permit_density = faces / area_km2 if area_km2 > 0 else None
            row.update({
                "permit_zone_block_face_count": faces,
                "permit_zone_count": len(permit["zones"]) if permit else 0,
                "permit_zone_buffer_block_faces": permit["buffer"] if permit else 0,
                PERMIT_METRIC: _round(permit_density),
            })
        rows.append(row)
    return rows


def _write_outputs(output_dir: Path, geo_key: str, rows: list[dict[str, Any]]) -> None:
    (output_dir / f"{geo_key}_parking_summary.json").write_text(json.dumps(rows, indent=2))
    if rows:
        fieldnames = list(rows[0].keys())
        with open(output_dir / f"{geo_key}_parking_summary.csv", "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


def run(
    *,
    parking_input: str | Path | None = None,
    permit_input: str | Path | None = None,
    complaints_input: str | Path | None = None,
    car_ownership_input: str | Path | None = None,
    complaints_since: str = complaints_311.DEFAULT_SINCE,
    acs_year: int = car_ownership.DEFAULT_YEAR,
    refresh: bool = False,
    overpass_url: str = parking_osm.OVERPASS_URL,
    reference_dir: Path | None = None,
    output_dir: str | Path = PROCESSED_DIR,
    collected_at: datetime | None = None,
) -> dict[str, Any]:
    indexes = load_all(reference_dir) if reference_dir else load_all()
    ward_index = indexes["ward"]

    if parking_input:
        parking_payload = parking_osm.load_cached(parking_input)
        parking_mode = f"cached:{parking_input}"
    else:
        parking_payload = parking_osm.fetch(ward_index.bounds, overpass_url=overpass_url, refresh=refresh)
        parking_mode = f"overpass:{overpass_url}"

    if permit_input:
        permit_rows = permit_zones.load_cached(permit_input)
        permit_mode = f"cached:{permit_input}"
    else:
        permit_rows = permit_zones.fetch(refresh=refresh)
        permit_mode = f"soda:{permit_zones.PERMIT_ZONES_URL}"

    if complaints_input:
        complaints_data = complaints_311.load_cached(complaints_input)
        complaints_mode = f"cached:{complaints_input}"
    else:
        complaints_data = complaints_311.fetch(since=complaints_since, refresh=refresh)
        complaints_mode = f"soda:{complaints_311.REQUESTS_URL} since {complaints_since}"
    complaints_counts = complaints_data["counts"]
    complaints_audit = complaints_data["audit"]

    # Car ownership / population is optional: it needs a free Census API key, so a
    # clone without one still produces the supply / scarcity / 311 metrics.
    car_ownership_note = None
    if car_ownership_input:
        tract_records = car_ownership.load_cached(car_ownership_input)
        car_ownership_mode = f"cached:{car_ownership_input}"
    else:
        try:
            tract_records = car_ownership.fetch(year=acs_year, refresh=refresh)
            car_ownership_mode = f"acs:{acs_year}"
        except RuntimeError as error:
            tract_records = []
            car_ownership_mode = "skipped"
            car_ownership_note = str(error)

    parking_accum, parking_audit = assign_parking(parking_payload, indexes)
    tracts_accum, tracts_audit = assign_tracts(tract_records, indexes)
    permit_by_ward, permit_audit = assign_permit_zones(permit_rows, ward_index)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries: dict[str, list[dict[str, Any]]] = {}
    for spec_key, index in indexes.items():
        permit_arg = permit_by_ward if spec_key == "ward" else None
        rows = build_summary(
            index.spec, index, parking_accum[spec_key], complaints_counts.get(spec_key, {}),
            tracts_accum[spec_key], permit_arg,
        )
        summaries[spec_key] = rows
        _write_outputs(output_dir, spec_key, rows)

    metadata = {
        "source": SOURCE_LABEL,
        "source_url": SOURCE_URL,
        "collected_at": (collected_at or datetime.now(UTC)).replace(microsecond=0).isoformat(),
        "metric_geography_coverage": {
            PARKING_METRIC: ["ward", "community_area", "zip"],
            COMPLAINTS_METRIC: ["ward", "community_area", "zip"],
            COMPLAINTS_SHARE_METRIC: ["ward", "community_area", "zip"],
            VEHICLES_METRIC: (["ward", "community_area", "zip"] if tract_records else []),
            PERMIT_METRIC: ["ward"],
        },
        "sources": {
            "offstreet_parking": {
                "name": "OpenStreetMap amenity=parking (Overpass)",
                "mode": parking_mode,
                "attribution": "© OpenStreetMap contributors (ODbL)",
                "caveat": "capacity tag is incomplete; site count is the robust measure.",
            },
            "parking_311_complaints": {
                "name": "Chicago 311 parking complaints (Data Portal v6vf-nfxy)",
                "mode": complaints_mode,
                "page": complaints_311.SOURCE_PAGE,
                "sr_types": list(complaints_311.PARKING_SR_TYPES),
                "since": complaints_since,
                "denominator_excluded_types": list(complaints_311.DENOMINATOR_EXCLUDED_TYPES),
                "share_metric": (
                    "parking_311_share_of_local_complaints_pct = parking complaints / all local "
                    "311 complaints (excluding info-only + aircraft-noise bulk types), to control "
                    "for how much each area reports overall."
                ),
                "caveat": (
                    "Current resident-reported signal (abandoned-vehicle + bike-lane parking "
                    "complaints). Reflects reporting propensity too; abandoned-vehicle reports "
                    "also track disinvestment, not only scarcity. One weighted signal, not the whole."
                ),
            },
            "car_ownership": {
                "name": "Census ACS 5-year B25044 (vehicles) + B01003 (population)",
                "mode": car_ownership_mode,
                "year": acs_year,
                "method": "tract values summed to geographies by tract centroid (gazetteer).",
                "note": car_ownership_note,
            },
            "permit_zones": {
                "name": "Chicago Residential Permit Zones (Data Portal u9xt-hiju)",
                "mode": permit_mode,
                "page": permit_zones.SOURCE_PAGE,
                "caveat": (
                    "Ward-level only (source has no geometry). A clean scarcity signal: "
                    "the city designates zones where street parking is contested; not "
                    "confounded by enforcement intensity the way ticket counts are."
                ),
            },
        },
        "audit": {**parking_audit, **complaints_audit, **tracts_audit, **permit_audit},
        "totals": {
            "wards": len(summaries["ward"]),
            "community_areas": len(summaries["community_area"]),
            "zips": len(summaries["zip"]),
        },
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    return {"summaries": summaries, "metadata": metadata}

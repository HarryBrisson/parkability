"""Bring-your-own-polygons aggregation.

Roll parkability's retained fine-grained features up to ANY GeoJSON polygons — not just the bundled
ward / community-area / ZIP boundaries. A consumer (e.g. ward-wise-explorer / Penlight) passes its own
areas plus the property that identifies them and gets back per-polygon metric values computed natively
from the underlying points, instead of an areal estimate off a fixed-geography rollup.

What can and can't be done this way:

* offstreet_parking_sites_per_sqkm, parking_311_complaints_per_sqkm, vehicles_per_household — computed
  here, because their source is retained as points (OSM parking, 311 parking complaints, ACS tract
  centroids) and point-in-polygon ÷ area works for any polygon.
* parking_311_share_of_local_complaints_pct — NOT here: its denominator is "all local 311 complaints,"
  aggregated server-side and not retained per point. Stays fixed-geography.
* permit_zone_block_faces_per_sqkm — NOT here: permit-zone block faces are ward-tagged address ranges
  with no point geometry. Stays fixed-geography.

Consumers should fall back to an areal estimate (e.g. ward → target by overlap) for the two
fixed-geography metrics. ``AGGREGATION_SPEC`` declares this per metric so a consumer can decide
programmatically.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .geographies import GeographyIndex, GeographySpec
from .pipeline import assign_parking, assign_tracts, build_summary

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"

# 311 service-request types that count as parking complaints (the others aren't retained as points).
ABANDONED_VEHICLE = "Abandoned Vehicle Complaint"
BIKE_LANE = "Vehicle Parked in Bike Lane Complaint"

# byop/v1 aggregation contract: a generic consumer reads this + the layer files and aggregates to its
# own polygons with no parkability code (combine in {count, ratio, share, mean}).
AGGREGATION_SPEC: dict[str, Any] = {
    "contract": "byop/v1",
    "source": "parkability",
    "source_url": "https://github.com/HarryBrisson/parkability",
    "layers": {
        "parking_sites": {"file": "parking_sites.geojson", "kind": "points"},
        "parking_complaints": {"file": "parking_complaints.geojson", "kind": "points"},
        "car_ownership": {"file": "car_ownership.geojson", "kind": "points"},
    },
    "metrics": {
        "offstreet_parking_sites_per_sqkm": {
            "layer": "parking_sites", "combine": "count", "per": "area_km2", "unit": "rate",
        },
        "parking_311_complaints_per_sqkm": {
            "layer": "parking_complaints", "combine": "count", "per": "area_km2", "unit": "rate",
        },
        "vehicles_per_household": {
            "layer": "car_ownership", "combine": "ratio", "numerator": "vehicles",
            "denominator": "households", "unit": "rate",
        },
    },
    "fixed_geography_metrics": {
        "parking_311_share_of_local_complaints_pct":
            "denominator is all local 311 complaints, aggregated server-side; not retained per point",
        "permit_zone_block_faces_per_sqkm":
            "permit-zone block faces are ward-tagged address ranges with no point geometry",
    },
}


def _assign_complaint_points(records: list[dict[str, Any]], index: GeographyIndex) -> dict[str, dict[str, int]]:
    """Point-in-polygon count of the retained 311 parking complaints per target area. ``local_total``
    stays 0 (the all-311 denominator isn't retained), so the share metric is omitted from the result."""
    accum: dict[str, dict[str, int]] = defaultdict(
        lambda: {"abandoned": 0, "bike_lane": 0, "parking_total": 0, "local_total": 0}
    )
    for record in records:
        lat, lng = record.get("latitude"), record.get("longitude")
        if lat is None or lng is None:
            continue
        area_id = index.assign(float(lat), float(lng))
        if area_id is None:
            continue
        bucket = accum[area_id]
        if record.get("sr_type") == BIKE_LANE:
            bucket["bike_lane"] += 1
        else:
            bucket["abandoned"] += 1
        bucket["parking_total"] += 1
    return dict(accum)


def aggregate_to_polygons(
    target_geojson: dict[str, Any],
    id_field: str,
    name_field: str | None = None,
    *,
    raw_dir: Path = RAW_DIR,
    parking_payload: dict[str, Any] | None = None,
    complaints: list[dict[str, Any]] | None = None,
    car_records: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Aggregate parkability's fine-grained features to ``target_geojson``'s polygons.

    Returns ``{area_id: {metric_id: value, ...}}`` for the BYOP metrics only (see AGGREGATION_SPEC).
    Each area also carries ``area_km2`` and the raw counts behind the rates. The retained point data is
    loaded from ``raw_dir`` unless passed in directly (handy for tests / alternate caches).
    """
    spec = GeographySpec("custom", "", id_field, name_field)
    index = GeographyIndex(spec, target_geojson)
    indexes = {"custom": index}

    if parking_payload is None:
        parking_payload = json.loads((raw_dir / "overpass_parking.json").read_text(encoding="utf-8"))
    if complaints is None:
        complaints = json.loads((raw_dir / "complaints_311.json").read_text(encoding="utf-8"))
    if car_records is None:
        car_records = json.loads((raw_dir / "acs_car_ownership.json").read_text(encoding="utf-8"))

    parking_accum, _ = assign_parking(parking_payload, indexes)
    tracts_accum, _ = assign_tracts(car_records, indexes)
    complaint_counts = _assign_complaint_points(complaints, index)

    rows = build_summary(
        spec,
        index,
        parking_accum["custom"],
        complaint_counts,
        tracts_accum["custom"],
        permit_by_ward=None,  # no geometry → fixed-geography only
    )

    byop_metrics = AGGREGATION_SPEC["metrics"]
    keep_counts = (
        "area_km2",
        "offstreet_parking_site_count",
        "parking_311_complaint_count",
        "households",
        "vehicles",
    )
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        area = {metric: row.get(metric) for metric in byop_metrics}
        area.update({field: row.get(field) for field in keep_counts})
        result[row["area_id"]] = area
    return result


def _point_feature(lng: float, lat: float, properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lng, lat]}, "properties": properties}


def write_byop_layers(output_dir: Path, *, raw_dir: Path = RAW_DIR) -> dict[str, int]:
    """Publish the fine-grained point layers + the aggregation spec so a consumer can bring its own
    polygons WITHOUT importing parkability — ingest the GeoJSON and run its own point-in-polygon."""
    from .sources import parking_osm

    output_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}

    parking_payload = json.loads((raw_dir / "overpass_parking.json").read_text(encoding="utf-8"))
    parking_features = [
        _point_feature(lng, lat, {"osm_type": osm_type, "osm_id": osm_id, "capacity": capacity, "parking_type": ptype})
        for osm_type, osm_id, lat, lng, capacity, ptype in parking_osm.iter_parking_sites(parking_payload)
    ]
    counts["parking_sites"] = len(parking_features)
    (output_dir / "parking_sites.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": parking_features})
    )

    complaints = json.loads((raw_dir / "complaints_311.json").read_text(encoding="utf-8"))
    complaint_features = [
        _point_feature(float(r["longitude"]), float(r["latitude"]), {"sr_type": r.get("sr_type")})
        for r in complaints
        if r.get("latitude") is not None and r.get("longitude") is not None
    ]
    counts["parking_complaints"] = len(complaint_features)
    (output_dir / "parking_complaints.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": complaint_features})
    )

    car_records = json.loads((raw_dir / "acs_car_ownership.json").read_text(encoding="utf-8"))
    car_features = [
        _point_feature(r["lng"], r["lat"], {"geoid": r.get("geoid"), "households": r["households"],
                                            "vehicles": r["vehicles"], "population": r["population"]})
        for r in car_records
    ]
    counts["car_ownership"] = len(car_features)
    (output_dir / "car_ownership.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": car_features})
    )

    (output_dir / "aggregation_spec.json").write_text(json.dumps(AGGREGATION_SPEC, indent=2))
    return counts


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Aggregate parkability metrics to your own polygons.")
    parser.add_argument("--polygons", type=Path, help="GeoJSON FeatureCollection of target areas")
    parser.add_argument("--id-field", default="area_id", help="property identifying each area")
    parser.add_argument("--name-field", default=None, help="optional property for a display name")
    parser.add_argument("--output", type=Path, help="write the {area_id: metrics} JSON here (else stdout)")
    parser.add_argument("--publish-layers", type=Path, help="write the fine-grained layers + spec to this dir")
    args = parser.parse_args(argv)

    if args.publish_layers:
        counts = write_byop_layers(args.publish_layers)
        print(f"wrote layers to {args.publish_layers}: {counts}")
        return 0
    if not args.polygons:
        parser.error("pass --polygons (to aggregate) or --publish-layers (to export the fine layers)")
    target = json.loads(args.polygons.read_text(encoding="utf-8"))
    result = aggregate_to_polygons(target, args.id_field, args.name_field)
    payload = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(payload)
        print(f"wrote {len(result)} areas to {args.output}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

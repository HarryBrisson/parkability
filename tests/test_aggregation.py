"""Bring-your-own-polygons aggregation: roll fine-grained features up to arbitrary target polygons."""
from __future__ import annotations

import json
from pathlib import Path

from parkability.aggregation import AGGREGATION_SPEC, aggregate_to_polygons

FIXTURES = Path(__file__).resolve().parent.parent / "data" / "fixtures"

# A box around the fixture points (~41.9, -87.68).
TARGET = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"cell_id": "A1", "label": "Test cell"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-87.70, 41.89], [-87.66, 41.89], [-87.66, 41.92], [-87.70, 41.92], [-87.70, 41.89]]],
            },
        }
    ],
}

# 311 parking complaints as points (the real cache is points; the bundled fixture is pre-aggregated).
COMPLAINT_POINTS = [
    {"sr_type": "Abandoned Vehicle Complaint", "latitude": 41.908, "longitude": -87.681},
    {"sr_type": "Vehicle Parked in Bike Lane Complaint", "latitude": 41.909, "longitude": -87.682},
    {"sr_type": "Abandoned Vehicle Complaint", "latitude": 40.0, "longitude": -88.0},  # far away -> excluded
]


def test_aggregate_to_polygons_produces_byop_metrics_only():
    parking = json.loads((FIXTURES / "sample_parking.json").read_text(encoding="utf-8"))
    cars = json.loads((FIXTURES / "sample_car_ownership.json").read_text(encoding="utf-8"))

    result = aggregate_to_polygons(
        TARGET,
        "cell_id",
        name_field="label",
        parking_payload=parking,
        complaints=COMPLAINT_POINTS,
        car_records=cars,
    )

    assert set(result) == {"A1"}
    cell = result["A1"]

    # the three BYOP metrics are computed natively for the custom polygon
    for metric in AGGREGATION_SPEC["metrics"]:
        assert cell.get(metric) is not None, metric

    # the fixed-geography metrics are NOT fabricated here
    assert "parking_311_share_of_local_complaints_pct" not in cell
    assert "permit_zone_block_faces_per_sqkm" not in cell

    # point-in-polygon only counts points inside the box (the far-away complaint is excluded)
    assert cell["parking_311_complaint_count"] == 2
    assert cell["offstreet_parking_site_count"] >= 1
    assert cell["area_km2"] > 0


def test_aggregation_spec_separates_byop_from_fixed():
    assert AGGREGATION_SPEC["contract"] == "byop/v1"
    assert set(AGGREGATION_SPEC["metrics"]) == {
        "offstreet_parking_sites_per_sqkm",
        "parking_311_complaints_per_sqkm",
        "vehicles_per_household",
    }
    assert set(AGGREGATION_SPEC["fixed_geography_metrics"]) == {
        "parking_311_share_of_local_complaints_pct",
        "permit_zone_block_faces_per_sqkm",
    }

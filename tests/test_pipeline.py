import json
from pathlib import Path

from parkability.pipeline import PARKING_METRIC, PERMIT_METRIC, run

FIXTURES = Path(__file__).resolve().parent.parent / "data" / "fixtures"
PARKING = FIXTURES / "sample_parking.json"
PERMIT = FIXTURES / "sample_permit_zones.json"


def _run(tmp_path):
    return run(parking_input=PARKING, permit_input=PERMIT, output_dir=tmp_path)


def test_writes_all_three_geographies(tmp_path):
    result = _run(tmp_path)
    for geo in ("ward", "community_area", "zip"):
        assert (tmp_path / f"{geo}_parking_summary.json").exists()
        assert (tmp_path / f"{geo}_parking_summary.csv").exists()
    assert (tmp_path / "metadata.json").exists()
    # Every geography lists all its areas (50 wards, 77 community areas).
    assert len(result["summaries"]["ward"]) == 50
    assert len(result["summaries"]["community_area"]) == 77


def test_parking_assignment_and_density(tmp_path):
    result = _run(tmp_path)
    by_ward = {r["area_id"]: r for r in result["summaries"]["ward"]}
    # Out-of-bounds site dropped; ward 01 has 3 sites, ward 02 has 1, ward 03 has 0.
    assert by_ward["01"]["offstreet_parking_site_count"] == 3
    assert by_ward["02"]["offstreet_parking_site_count"] == 1
    assert by_ward["03"]["offstreet_parking_site_count"] == 0
    # 5 sites in source (4 in-city + 1 out-of-bounds); the OOB one assigns nowhere.
    assert result["metadata"]["audit"]["parking_sites_total"] == 5
    assert sum(r["offstreet_parking_site_count"] for r in result["summaries"]["ward"]) == 4
    # Capacity summed only where tagged (40 in one ward-01 site).
    assert by_ward["01"]["offstreet_parking_capacity_spaces"] == 40
    assert by_ward["01"]["offstreet_parking_capacity_known_sites"] == 1
    # Density = sites / area_km2, non-negative.
    assert by_ward["01"][PARKING_METRIC] >= 0


def test_permit_zones_ward_only_with_buffer_and_crossward(tmp_path):
    result = _run(tmp_path)
    by_ward = {r["area_id"]: r for r in result["summaries"]["ward"]}
    # Ward 01: 3 same-ward ACTIVE faces + 1 cross-ward face = 4; INACTIVE excluded.
    assert by_ward["01"]["permit_zone_block_face_count"] == 4
    assert by_ward["01"]["permit_zone_buffer_block_faces"] == 1
    assert by_ward["01"]["permit_zone_count"] == 3  # zones 10, 11, 30
    # Ward 02: its own face + the cross-ward face = 2.
    assert by_ward["02"]["permit_zone_block_face_count"] == 2
    assert by_ward["01"][PERMIT_METRIC] >= 0


def test_permit_metric_absent_from_non_ward_geographies(tmp_path):
    result = _run(tmp_path)
    ca_row = result["summaries"]["community_area"][0]
    assert PERMIT_METRIC not in ca_row  # ward-only until geocoded
    assert PARKING_METRIC in ca_row
    coverage = result["metadata"]["metric_geography_coverage"]
    assert coverage[PERMIT_METRIC] == ["ward"]
    assert set(coverage[PARKING_METRIC]) == {"ward", "community_area", "zip"}


def test_zero_area_or_empty_area_handling(tmp_path):
    result = _run(tmp_path)
    # Areas with no parking still appear with a 0 count and a real (>=0) density.
    for row in result["summaries"]["ward"]:
        assert row["offstreet_parking_site_count"] >= 0
        assert row[PARKING_METRIC] is None or row[PARKING_METRIC] >= 0

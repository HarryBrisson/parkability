"""Car ownership and population from the Census ACS 5-year API (the demand side).

Pulls, per Cook County census tract:
  * B25044 — Tenure by Vehicles Available → aggregate vehicles + total households
  * B01003 — total population (for per-capita normalization)

Tracts are joined to bundled centroids (data/reference/cook_tract_centroids.csv,
from the Census gazetteer) and the pipeline point-assigns each centroid to a
ward / community area / zip. Tract-to-geography by centroid is an approximation,
but tracts are small relative to wards so it is accurate enough for this metric
and keeps the repo shapely-free.

The ACS API requires a free key. Set CENSUS_API_KEY in the environment
(https://api.census.gov/data/key_signup.html).
"""

from __future__ import annotations

import csv
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CACHE = REPO_ROOT / "data" / "raw" / "acs_car_ownership.json"
DEFAULT_CENTROIDS = REPO_ROOT / "data" / "reference" / "cook_tract_centroids.csv"
ACS_API_BASE = "https://api.census.gov/data/{year}/acs/acs5"
DEFAULT_YEAR = 2023
COOK_COUNTY = {"state": "17", "county": "031"}
API_KEY_ENV = "CENSUS_API_KEY"

# Households by vehicles available (owner + renter), weighted by vehicle count.
# 5-or-more is approximated as 5.
VEHICLE_LEVELS = {
    1: ("B25044_004E", "B25044_011E"),
    2: ("B25044_005E", "B25044_012E"),
    3: ("B25044_006E", "B25044_013E"),
    4: ("B25044_007E", "B25044_014E"),
    5: ("B25044_008E", "B25044_015E"),
}
TOTAL_HOUSEHOLDS = "B25044_001E"
POPULATION = "B01003_001E"
ACS_VARS = [TOTAL_HOUSEHOLDS, POPULATION, *(v for pair in VEHICLE_LEVELS.values() for v in pair)]


def load_centroids(path: Path | str = DEFAULT_CENTROIDS) -> dict[str, tuple[float, float]]:
    centroids: dict[str, tuple[float, float]] = {}
    with open(path, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            centroids[row["geoid"]] = (float(row["lat"]), float(row["lng"]))
    return centroids


def _int(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if n >= 0 else 0  # ACS uses negatives as missing/annotation flags


def fetch(
    *,
    year: int = DEFAULT_YEAR,
    api_key: str | None = None,
    centroids_path: Path | str = DEFAULT_CENTROIDS,
    cache_path: Path | str = DEFAULT_CACHE,
    refresh: bool = False,
    timeout_seconds: float = 120.0,
) -> list[dict[str, Any]]:
    """Return tract records [{geoid, lat, lng, vehicles, households, population}]."""
    cache_path = Path(cache_path)
    if cache_path.exists() and not refresh:
        with open(cache_path, encoding="utf-8") as handle:
            return json.load(handle)

    key = api_key or os.getenv(API_KEY_ENV)
    if not key:
        raise RuntimeError(
            f"Census ACS API requires a key. Set {API_KEY_ENV} "
            "(free: https://api.census.gov/data/key_signup.html)."
        )

    params = urllib.parse.urlencode({
        "get": ",".join(ACS_VARS),
        "for": "tract:*",
        "in": f"state:{COOK_COUNTY['state']} county:{COOK_COUNTY['county']}",
        "key": key,
    })
    url = f"{ACS_API_BASE.format(year=year)}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            table = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise RuntimeError(f"ACS fetch failed: {error}") from error

    header = table[0]
    idx = {name: header.index(name) for name in header}
    centroids = load_centroids(centroids_path)

    records: list[dict[str, Any]] = []
    for row in table[1:]:
        geoid = f"{row[idx['state']]}{row[idx['county']]}{row[idx['tract']]}"
        centroid = centroids.get(geoid)
        if centroid is None:
            continue
        households = _int(row[idx[TOTAL_HOUSEHOLDS]])
        vehicles = sum(
            level * (_int(row[idx[owner]]) + _int(row[idx[renter]]))
            for level, (owner, renter) in VEHICLE_LEVELS.items()
        )
        records.append({
            "geoid": geoid,
            "lat": centroid[0],
            "lng": centroid[1],
            "households": households,
            "vehicles": vehicles,
            "population": _int(row[idx[POPULATION]]),
        })

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as handle:
        json.dump(records, handle)
    return records


def load_cached(path: Path | str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)

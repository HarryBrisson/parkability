"""Parking-related 311 service requests from the Chicago Data Portal (v6vf-nfxy).

Resident-reported parking dysfunction — a *current* stress signal, unlike the
2007–2018 parking-ticket set. Two request types are parking-occupancy related:

* "Vehicle Parked in Bike Lane Complaint" — a literal illegal-parking report.
* "Abandoned Vehicle Complaint" — the long-standing nuisance-parking report.

Each record carries latitude/longitude, so it point-assigns to ward / community
area / zip like the OSM parking sites. We bound the pull to a recent window
(default since 2023) so the signal reflects current conditions.

Methodology caveat (kept honest per the repo's sourcing rules): complaint counts
reflect *reporting propensity* as well as actual conditions, and abandoned-vehicle
reports also track disinvestment, not only scarcity. Treat as one weighted signal,
never the sole measure.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CACHE = REPO_ROOT / "data" / "raw" / "complaints_311.json"
REQUESTS_URL = "https://data.cityofchicago.org/resource/v6vf-nfxy.json"
SOURCE_PAGE = "https://data.cityofchicago.org/Service-Requests/311-Service-Requests/v6vf-nfxy"

PARKING_SR_TYPES = (
    "Abandoned Vehicle Complaint",
    "Vehicle Parked in Bike Lane Complaint",
)
DEFAULT_SINCE = "2023-01-01"

SHORT_TYPE = {
    "Abandoned Vehicle Complaint": "abandoned",
    "Vehicle Parked in Bike Lane Complaint": "bike_lane",
}


def fetch(
    *,
    url: str = REQUESTS_URL,
    since: str = DEFAULT_SINCE,
    cache_path: Path | str = DEFAULT_CACHE,
    refresh: bool = False,
    page_size: int = 50000,
    timeout_seconds: float = 120.0,
) -> list[dict[str, Any]]:
    cache_path = Path(cache_path)
    if cache_path.exists() and not refresh:
        with open(cache_path, encoding="utf-8") as handle:
            return json.load(handle)

    type_list = ",".join(f"'{t}'" for t in PARKING_SR_TYPES)
    where = f"sr_type in ({type_list}) AND created_date >= '{since}'"
    select = "sr_type,latitude,longitude,ward,community_area,zip_code,created_date,status"
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        params = urllib.parse.urlencode({
            "$select": select, "$where": where, "$limit": page_size, "$offset": offset,
        })
        request = urllib.request.Request(f"{url}?{params}", headers={"User-Agent": "parkability/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                page = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise RuntimeError(f"311 fetch failed at offset {offset}: {error}") from error
        if not page:
            break
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as handle:
        json.dump(rows, handle)
    return rows


def load_cached(path: Path | str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def iter_complaints(rows: list[dict[str, Any]]):
    """Yield (lat, lng, short_type) for each record with usable coordinates."""
    for row in rows:
        lat = row.get("latitude")
        lng = row.get("longitude")
        if lat in (None, "") or lng in (None, ""):
            continue
        short = SHORT_TYPE.get(row.get("sr_type"))
        if short is None:
            continue
        try:
            yield float(lat), float(lng), short
        except (TypeError, ValueError):
            continue

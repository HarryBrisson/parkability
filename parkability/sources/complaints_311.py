"""Parking-related 311 service requests from the Chicago Data Portal (v6vf-nfxy).

Resident-reported parking dysfunction — a *current* stress signal, unlike the
2007–2018 parking-ticket set. Two request types are parking-occupancy related:

* "Vehicle Parked in Bike Lane Complaint" — a literal illegal-parking report.
* "Abandoned Vehicle Complaint" — the long-standing nuisance-parking report.

We aggregate counts by the record's built-in `ward` / `community_area` /
`zip_code` columns (cheap SODA group-by, no row dumps), and also count a
denominator of "local" complaints so we can express parking as a **share of
local 311 activity** — which controls for the fact that some areas simply report
more of everything.

The denominator deliberately EXCLUDES two non-neighborhood bulk types that
otherwise swamp it: "311 INFORMATION ONLY CALL" (~2.3M) and "Aircraft Noise
Complaint" (~1.2M, almost all around O'Hare). Without that exclusion the share is
meaningless.

Caveat (kept honest): complaint counts reflect reporting propensity too, and
abandoned-vehicle reports track disinvestment, not only scarcity. One weighted
signal, never the whole picture.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CACHE = REPO_ROOT / "data" / "raw" / "complaints_311_counts.json"
REQUESTS_URL = "https://data.cityofchicago.org/resource/v6vf-nfxy.json"
SOURCE_PAGE = "https://data.cityofchicago.org/Service-Requests/311-Service-Requests/v6vf-nfxy"

PARKING_SR_TYPES = (
    "Abandoned Vehicle Complaint",
    "Vehicle Parked in Bike Lane Complaint",
)
SHORT_TYPE = {
    "Abandoned Vehicle Complaint": "abandoned",
    "Vehicle Parked in Bike Lane Complaint": "bike_lane",
}
# Bulk request types that are not neighborhood conditions; excluded from the
# "local complaints" denominator so the parking share stays comparable.
DENOMINATOR_EXCLUDED_TYPES = (
    "311 INFORMATION ONLY CALL",
    "Aircraft Noise Complaint",
)
DEFAULT_SINCE = "2023-01-01"

# geography key -> the 311 column carrying that geography, and whether to zero-pad.
GEO_COLUMN = {"ward": ("ward", 2), "community_area": ("community_area", 2), "zip": ("zip_code", 0)}


def _normalize(value: Any, pad: int) -> str | None:
    text = str(value).strip() if value not in (None, "") else ""
    if not text:
        return None
    if pad and text.isdigit():
        return f"{int(text):0{pad}d}"
    return text


def _soda(url: str, params: dict[str, Any], timeout_seconds: float) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": "parkability/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise RuntimeError(f"311 fetch failed: {error}") from error


def _quote_list(values) -> str:
    return ",".join(f"'{v}'" for v in values)


def fetch(
    *,
    url: str = REQUESTS_URL,
    since: str = DEFAULT_SINCE,
    cache_path: Path | str = DEFAULT_CACHE,
    refresh: bool = False,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Return {"counts": {geo_key: {area_id: {...}}}, "audit": {...}} by group-by."""
    cache_path = Path(cache_path)
    if cache_path.exists() and not refresh:
        with open(cache_path, encoding="utf-8") as handle:
            return json.load(handle)

    parking_where = f"sr_type in ({_quote_list(PARKING_SR_TYPES)}) AND created_date >= '{since}'"
    local_where = (
        f"sr_type not in ({_quote_list(DENOMINATOR_EXCLUDED_TYPES)}) AND created_date >= '{since}'"
    )

    counts: dict[str, dict[str, dict[str, int]]] = {}
    for geo_key, (column, pad) in GEO_COLUMN.items():
        area: dict[str, dict[str, int]] = {}
        for row in _soda(url, {
            "$select": f"{column},sr_type,count(*) as n",
            "$where": f"{parking_where} AND {column} IS NOT NULL",
            "$group": f"{column},sr_type", "$limit": 100000,
        }, timeout_seconds):
            area_id = _normalize(row.get(column), pad)
            if area_id is None:
                continue
            bucket = area.setdefault(area_id, {"abandoned": 0, "bike_lane": 0, "parking_total": 0, "local_total": 0})
            short = SHORT_TYPE.get(row.get("sr_type"))
            n = int(row.get("n", 0))
            if short:
                bucket[short] += n
                bucket["parking_total"] += n
        for row in _soda(url, {
            "$select": f"{column},count(*) as n",
            "$where": f"{local_where} AND {column} IS NOT NULL",
            "$group": column, "$limit": 100000,
        }, timeout_seconds):
            area_id = _normalize(row.get(column), pad)
            if area_id is None:
                continue
            bucket = area.setdefault(area_id, {"abandoned": 0, "bike_lane": 0, "parking_total": 0, "local_total": 0})
            bucket["local_total"] += int(row.get("n", 0))
        counts[geo_key] = area

    audit = {
        "since": since,
        "denominator_excluded_types": list(DENOMINATOR_EXCLUDED_TYPES),
        "parking_complaints_ward_total": sum(b["parking_total"] for b in counts["ward"].values()),
    }
    result = {"counts": counts, "audit": audit}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle)
    return result


def load_cached(path: Path | str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)

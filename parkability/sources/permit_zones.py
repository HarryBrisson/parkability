"""Residential Permit Zones from the Chicago Data Portal (dataset u9xt-hiju).

This dataset has NO geometry — each row is a block-face address range already
tagged with the ward(s) it falls in (`ward_low`/`ward_high`) plus its permit
`zone`, `status`, and a `buffer` flag (buffer = no physical signs, residents may
still buy zone products). Because the ward is built in, the ward rollup needs no
geocoding. Community-area / ZIP rollups require geocoding the block faces and are
handled in a later phase; this module exposes only what the source provides.

The city designates these zones where residents compete for scarce street
parking, which makes their density a clean "hard to park here" policy signal —
and, unlike ticket counts, it is not confounded by enforcement intensity.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CACHE = REPO_ROOT / "data" / "raw" / "permit_zones.json"
PERMIT_ZONES_URL = "https://data.cityofchicago.org/resource/u9xt-hiju.json"
SOURCE_PAGE = "https://data.cityofchicago.org/Transportation/Parking-Permit-Zones/u9xt-hiju"


def fetch(
    *,
    url: str = PERMIT_ZONES_URL,
    cache_path: Path | str = DEFAULT_CACHE,
    refresh: bool = False,
    page_size: int = 50000,
    timeout_seconds: float = 120.0,
) -> list[dict[str, Any]]:
    cache_path = Path(cache_path)
    if cache_path.exists() and not refresh:
        with open(cache_path, encoding="utf-8") as handle:
            return json.load(handle)

    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page_url = f"{url}?$limit={page_size}&$offset={offset}"
        request = urllib.request.Request(page_url, headers={"User-Agent": "parkability/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                page = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise RuntimeError(f"Permit-zone fetch failed at offset {offset}: {error}") from error
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


def normalize_ward_id(value: Any) -> str | None:
    text = str(value).strip() if value not in (None, "") else ""
    if not text or not text.isdigit():
        return None
    return f"{int(text):02d}"


def iter_active_block_faces(rows: list[dict[str, Any]]):
    """Yield (ward_id, zone, is_buffer) for each ACTIVE permit-zone block face.

    A block face spanning two wards (ward_low != ward_high) is counted toward
    both wards, since it borders permit-controlled parking in each.
    """
    for row in rows:
        if str(row.get("status", "")).strip().upper() != "ACTIVE":
            continue
        zone = str(row.get("zone", "")).strip() or None
        is_buffer = str(row.get("buffer", "")).strip().upper() == "Y"
        wards = {normalize_ward_id(row.get("ward_low")), normalize_ward_id(row.get("ward_high"))}
        for ward_id in wards:
            if ward_id:
                yield ward_id, zone, is_buffer

"""Off-street parking supply from OpenStreetMap via the Overpass API.

Pulls `amenity=parking` features (garages, lots, underground) within the city
bounding box. Each feature carries an optional `capacity` (number of spaces);
many do not, so the pipeline reports both a robust site count and the summed
capacity where tagged. Mirrors chainshare's Overpass approach (bbox query,
cache to data/raw/, re-runnable offline via --input).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CACHE = REPO_ROOT / "data" / "raw" / "overpass_parking.json"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def build_query(bounds: tuple[float, float, float, float]) -> str:
    bbox = f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}"
    return (
        "[out:json][timeout:180];\n(\n"
        f'  node["amenity"="parking"]({bbox});\n'
        f'  way["amenity"="parking"]({bbox});\n'
        f'  relation["amenity"="parking"]({bbox});\n'
        ");\nout center tags;"
    )


def fetch(
    bounds: tuple[float, float, float, float],
    *,
    overpass_url: str = OVERPASS_URL,
    cache_path: Path | str = DEFAULT_CACHE,
    refresh: bool = False,
    attempts: int = 3,
    backoff_seconds: float = 5.0,
    timeout_seconds: float = 240.0,
) -> dict[str, Any]:
    cache_path = Path(cache_path)
    if cache_path.exists() and not refresh:
        with open(cache_path, encoding="utf-8") as handle:
            return json.load(handle)

    data = build_query(bounds).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(
                overpass_url,
                data=data,
                headers={
                    "User-Agent": "parkability/1.0 (https://github.com/) civic-data",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            return payload
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            last_error = error
            if attempt < attempts:
                time.sleep(backoff_seconds * attempt)
    raise RuntimeError(f"Overpass parking fetch failed after {attempts} attempts: {last_error}")


def load_cached(path: Path | str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _capacity(tags: dict[str, str]) -> int | None:
    raw = tags.get("capacity")
    if raw is None:
        return None
    try:
        return max(0, int(float(str(raw).strip())))
    except (TypeError, ValueError):
        return None


def iter_parking_sites(payload: dict[str, Any]):
    """Yield (osm_type, osm_id, lat, lng, capacity, parking_type) per feature."""
    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        if tags.get("amenity") != "parking":
            continue
        lat = element.get("lat")
        lng = element.get("lon")
        if lat is None or lng is None:
            center = element.get("center") or {}
            lat, lng = center.get("lat"), center.get("lon")
        if lat is None or lng is None:
            continue
        yield (
            element.get("type", "node"),
            element.get("id"),
            float(lat),
            float(lng),
            _capacity(tags),
            tags.get("parking"),
        )

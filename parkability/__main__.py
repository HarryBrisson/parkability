"""Command-line entry point: ``python -m parkability``."""

from __future__ import annotations

import argparse
import json

from .pipeline import run
from .sources import parking_osm


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="parkability",
        description="Build Chicago parking metrics by ward / community area / zip.",
    )
    parser.add_argument("--parking-input", help="Cached Overpass parking JSON; skips the network fetch.")
    parser.add_argument("--permit-input", help="Cached permit-zone JSON; skips the network fetch.")
    parser.add_argument("--refresh", action="store_true", help="Force fresh fetches even if cached.")
    parser.add_argument("--overpass-url", default=parking_osm.OVERPASS_URL)
    parser.add_argument("--reference-dir", help="Override the bundled boundary directory.")
    parser.add_argument("--output-dir", help="Override the output directory (default: data/processed).")
    args = parser.parse_args(argv)

    result = run(
        parking_input=args.parking_input,
        permit_input=args.permit_input,
        refresh=args.refresh,
        overpass_url=args.overpass_url,
        reference_dir=args.reference_dir,
        output_dir=args.output_dir or run.__globals__["PROCESSED_DIR"],
    )
    print(json.dumps(result["metadata"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

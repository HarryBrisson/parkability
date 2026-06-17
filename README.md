# parkability

**How easy is it to park, by Chicago ward / community area / ZIP — from open data.**

A [ward-wise-civic-tech](https://github.com/) *direct metric* source, sibling to
[`chainshare`](https://github.com/HarryBrisson/chainshare). "Ease of parking" is a latent
construct, so rather than one opaque score, parkability publishes **clean component
metrics** that the Penlight explorer lets you weight yourself. It models parking as
**supply vs. scarcity**.

> Latest run: **13,748** off-street parking sites · **10,005** active permit-zone block
> faces · 50 wards / 77 community areas / 59 ZIPs.

## Metrics (Phase 1)

| metric | meaning | geographies | toward "easier to park" |
| --- | --- | --- | --- |
| `offstreet_parking_sites_per_sqkm` | OSM off-street parking density (supply) | ward · community area · zip | higher |
| `permit_zone_block_faces_per_sqkm` | residential permit-zone density (scarcity) | ward | lower |

The permit-zone signal is deliberately central: the city designates these zones *where
residents compete for scarce street parking*, so it's a clean "hard to park here" signal —
and, unlike ticket counts, **it is not confounded by enforcement intensity**.

Validation from real data: permit-zone density peaks in the dense North/Central wards
(Lakeview, Lincoln Park, River North, Wicker Park) and bottoms out on the periphery;
off-street supply concentrates downtown (the Loop alone tags ~9,900 garage spaces).

## Roadmap (Phase 2)

- `vehicles_per_household` (ACS B25044) and population normalization (ACS B01003) → per-capita supply.
- `parking_tickets_per_1000_residents_2018` — illegal-parking density, **clearly dated**
  (the only comprehensive public set ends May 2018; refresh requires a FOIA to the Dept. of
  Finance) and **enforcement-biased** (normalized + caveated, never raw).
- Geocode permit-zone block faces → community-area / ZIP permit coverage (the source has no
  geometry, only built-in ward assignment, so those rollups need a one-time geocode).

Excluded by design: a single composite index; car-related crime (a weak, confounded proxy);
metered-space supply (no clean official open feed).

## Outputs

`data/processed/`:

| File | Grain |
| --- | --- |
| `ward_parking_summary.json` | one row per ward — **the rollup Penlight ingests** |
| `community_area_parking_summary.json` | one row per community area |
| `zip_parking_summary.json` | one row per ZIP |
| `*.csv` | tabular twins |
| `metadata.json` | provenance, per-metric geography coverage, caveats, audit |

## Run it

```bash
python -m parkability                 # live fetch (OSM Overpass + Chicago Data Portal)
python -m parkability --refresh       # force fresh fetch
python -m parkability \
  --parking-input data/fixtures/sample_parking.json \
  --permit-input data/fixtures/sample_permit_zones.json   # offline (tests use these)
```

Standard library only — point-in-polygon, length, and area math are pure Python
(`geometry.py`, `measure.py`); no shapely/geopandas. Tests: `python -m pytest`.

## Sources & attribution

- Off-street parking: **© OpenStreetMap contributors** ([ODbL](https://www.openstreetmap.org/copyright)), via Overpass.
- Permit zones: **Chicago Data Portal** — [Residential Permit Zones `u9xt-hiju`](https://data.cityofchicago.org/Transportation/Parking-Permit-Zones/u9xt-hiju) (updated daily).
- Boundaries: ward + community area from ward-wise-civic-tech; ZIP from the Chicago Data Portal.

## License

Code: MIT. Derived data inherits its sources' licenses (OSM data under ODbL).

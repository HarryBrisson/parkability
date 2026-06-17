# parkability

**How easy is it to park, by Chicago ward / community area / ZIP — from open data.**

A [ward-wise-civic-tech](https://github.com/) *direct metric* source, sibling to
[`chainshare`](https://github.com/HarryBrisson/chainshare). "Ease of parking" is a latent
construct, so rather than one opaque score, parkability publishes **clean component
metrics** that the Penlight explorer lets you weight yourself. It models parking as
**supply vs. scarcity**.

> Latest run: **13,748** off-street parking sites · **10,005** active permit-zone block
> faces · 50 wards / 77 community areas / 59 ZIPs.

## Metrics

| metric | meaning | geographies | toward "easier to park" |
| --- | --- | --- | --- |
| `offstreet_parking_sites_per_sqkm` | OSM off-street parking density (supply) | ward · community area · zip | higher |
| `parking_311_complaints_per_sqkm` | 311 abandoned-vehicle + bike-lane parking complaints (stress) | ward · community area · zip | lower |
| `parking_311_share_of_local_complaints_pct` | parking complaints as a share of local 311 activity (reporting-controlled) | ward · community area · zip | lower |
| `vehicles_per_household` | ACS cars per household (demand) | ward · community area · zip | lower |
| `permit_zone_block_faces_per_sqkm` | residential permit-zone density (scarcity) | ward | lower |

The **share** metric expresses parking complaints as a fraction of all *local* 311 activity
(excluding the `311 INFORMATION ONLY CALL` and `Aircraft Noise Complaint` bulk types, which
otherwise swamp the denominator — aircraft-noise alone is ~1.2M reports, nearly all in the
O'Hare ward). This controls for how much each area reports overall.

The permit-zone signal is deliberately central: the city designates these zones *where
residents compete for scarce street parking*, so it's a clean "hard to park here" signal —
and, unlike ticket counts, **it is not confounded by enforcement intensity**.

**These are separate, weightable components, not one score, because they measure different
things.** Validated against real data:
- Permit-zone density peaks in dense North/Central wards (Lakeview, Lincoln Park, River
  North, Wicker Park) and bottoms out on the periphery — a clean scarcity signal.
- Off-street supply concentrates downtown (the Loop alone tags ~9,900 garage spaces).
- Car ownership is lowest in the transit-dense North lakefront / downtown (Ward 2: 0.56
  veh/household) and highest in the SW/NW bungalow belt (Ward 23: 1.85) — the demand side.
- 311 parking complaints peak in NW/W working-class wards (Belmont Cragin, Portage Park) and
  are lowest in the dense, scarce-parking North/Central wards — **even as a reporting-controlled
  share** (9% of local 311 in the top wards vs ~2% in the Loop / Lincoln Park / River North).
  So this signal is genuinely *anti-correlated* with scarcity: it tracks vehicle-nuisance, a
  different dimension. (The truer "illegal parking" subtype, bike-lane complaints, is kept as a
  breakdown but is sparse — ~3.2k since 2023.) Methodology discloses this; weight accordingly.

## Roadmap

- `parking_tickets_per_1000_residents_2018` — illegal-parking density, **clearly dated**
  (the only comprehensive public set ends May 2018; refresh requires a FOIA to the Dept. of
  Finance) and **enforcement-biased** (normalized + caveated, never raw). Lower priority now
  that current 311 complaints cover the resident-report angle.
- Geocode permit-zone block faces → community-area / ZIP permit coverage (the source has no
  geometry, only built-in ward assignment, so those rollups need a one-time geocode).

Excluded by design: a single composite index; car-related crime (a weak, confounded proxy);
metered-space supply (no clean official open feed).

## Nomination

This metric was **nominated by a resident of Ward 1** — see [NOMINATION.md](NOMINATION.md).

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
python -m parkability                 # live fetch (OSM Overpass + Chicago Data Portal + ACS)
python -m parkability --refresh       # force fresh fetch
python -m parkability \
  --parking-input    data/fixtures/sample_parking.json \
  --permit-input     data/fixtures/sample_permit_zones.json \
  --complaints-input data/fixtures/sample_311.json \
  --car-ownership-input data/fixtures/sample_car_ownership.json   # offline (tests use these)
```

The car-ownership metric needs a **free Census API key** — set `CENSUS_API_KEY`
(https://api.census.gov/data/key_signup.html). Without it the run still produces the
supply / scarcity / 311 metrics and just skips `vehicles_per_household`.

Standard library only — point-in-polygon, length, and area math are pure Python
(`geometry.py`, `measure.py`); no shapely/geopandas. Tests: `python -m pytest`.

## Sources & attribution

- Off-street parking: **© OpenStreetMap contributors** ([ODbL](https://www.openstreetmap.org/copyright)), via Overpass.
- Permit zones: **Chicago Data Portal** — [Residential Permit Zones `u9xt-hiju`](https://data.cityofchicago.org/Transportation/Parking-Permit-Zones/u9xt-hiju) (updated daily).
- Boundaries: ward + community area from ward-wise-civic-tech; ZIP from the Chicago Data Portal.

## License

Code: MIT. Derived data inherits its sources' licenses (OSM data under ODbL).

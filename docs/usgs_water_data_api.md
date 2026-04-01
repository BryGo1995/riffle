# USGS Water Data API Reference

The new USGS Water Data API (`api.waterdata.usgs.gov`) replaces the legacy NWIS web services (`waterservices.usgs.gov`). It follows the OGC API standard and returns GeoJSON instead of RDB tab-delimited text.

## Base URL

```
https://api.waterdata.usgs.gov/ogcapi/v0
```

## Authentication

An API key is required for production use (without one you hit very low rate limits and will receive `429` responses).

**Two equivalent methods:**

| Method | How |
|--------|-----|
| Query parameter | `?api_key=YOUR_KEY` |
| HTTP header | `X-Api-Key: YOUR_KEY` |

Rate limit status is returned in response headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`.

The project API key is stored in `USGS_API_KEY` env var (see `.env` / docker-compose secrets).

## Migration from Legacy NWIS

| Legacy endpoint | New endpoint |
|-----------------|--------------|
| `waterservices.usgs.gov/nwis/site/` | `api.waterdata.usgs.gov/ogcapi/v0/collections/monitoring-locations/items` |
| `waterservices.usgs.gov/nwis/iv/` | `api.waterdata.usgs.gov/ogcapi/v0/collections/...` (see Time Series section) |

### Parameter mapping

| Legacy param | New param | Notes |
|---|---|---|
| `stateCd=CO` | `state_code=08` | Now uses 2-digit numeric FIPS code, not postal abbreviation |
| `siteType=ST` | `site_type_code=ST` | Same code values |
| `siteStatus=active` | *(no equivalent)* | Use `time-series-metadata` collection to find sites with recent data |
| `format=rdb` | `f=json` | GeoJSON is the default; also supports `f=csv`, `f=html` |

### State FIPS codes (common)

| State | Code |
|-------|------|
| Colorado | `08` |
| Montana | `30` |
| Wyoming | `56` |
| Utah | `49` |
| New Mexico | `35` |

Full list: https://www.census.gov/library/reference/code-lists/ansi/ansi-codes-for-states.html

## Collections

### `monitoring-locations` — Site metadata

```
GET /collections/monitoring-locations/items
```

**Key query params:**

| Param | Example | Description |
|-------|---------|-------------|
| `state_code` | `08` | Numeric FIPS state code |
| `site_type_code` | `ST` | Site type (ST=Stream, LK=Lake, GW=Groundwater well, AT=Atmosphere, ES=Estuary, LK=Lake/pond/reservoir, OC=Ocean, SP=Spring, WE=Wetland) |
| `limit` | `1000` | Results per page (max 10000) |
| `offset` | `0` | Pagination offset |
| `f` | `json` | Response format |
| `api_key` | `...` | Your API key |

**Response:** GeoJSON `FeatureCollection`

```json
{
  "type": "FeatureCollection",
  "numberReturned": 847,
  "features": [
    {
      "type": "Feature",
      "id": "USGS-06611000",
      "geometry": {
        "type": "Point",
        "coordinates": [-106.123, 40.456]
      },
      "properties": {
        "id": "USGS-06611000",
        "agency_code": "USGS",
        "monitoring_location_number": "06611000",
        "monitoring_location_name": "COLORADO CREEK NEAR SPICER, CO.",
        "state_code": "08",
        "state_name": "Colorado",
        "county_code": "...",
        "county_name": "...",
        "site_type_code": "ST",
        "site_type": "Stream",
        "hydrologic_unit_code": "14010001",
        "altitude": 9045.0,
        "time_zone_abbreviation": "MST",
        "uses_daylight_savings": "Y",
        "drainage_area": 42.3
      }
    }
  ]
}
```

**Important:** `numberMatched` (total count) is NOT returned. Paginate by checking if `numberReturned < limit` — when true, you're on the last page.

**Pagination pattern:**
```python
offset = 0
limit = 1000
while True:
    resp = requests.get(SITES_URL, params={..., "limit": limit, "offset": offset})
    features = resp.json()["features"]
    all_features.extend(features)
    if resp.json()["numberReturned"] < limit:
        break
    offset += limit
```

### `time-series-metadata` — Which parameters are available at a site

Use this collection to find sites with active/recent data (since `monitoring-locations` has no `siteStatus` filter) and to query by parameter code.

**Look up what a single site measures:**
```
GET /collections/time-series-metadata/items?monitoring_location_id=USGS-09085000
```

**Find all Colorado sites measuring discharge:**
```
GET /collections/time-series-metadata/items?parameter_code=00060&state_name=Colorado&limit=1000&f=json
```

Note: use `state_name=Colorado`, NOT `state_code=08` — `state_code` is not a valid filter on this collection and returns an `InvalidQuery` error.

**Key flow parameter codes:**

| Code | Name | Unit | Notes |
|------|------|------|-------|
| `00060` | Discharge | ft³/s | Primary streamflow parameter |
| `00065` | Gage height | ft | Raw stage reading; discharge derived from this via rating curve |
| `00010` | Temperature, water | degC | |
| `00095` | Specific conductance | uS/cm | |
| `00300` | Dissolved oxygen | mg/l | |
| `00400` | pH | pH units | |
| `63680` | Turbidity | FNU | |

**Fields returned per feature:**

| Field | Description |
|-------|-------------|
| `monitoring_location_id` | e.g. `USGS-09085000` |
| `parameter_code` | 5-digit USGS code |
| `parameter_name` | Short name, e.g. `Discharge` |
| `parameter_description` | Verbose, e.g. `Discharge, cubic feet per second` |
| `unit_of_measure` | e.g. `ft^3/s` |
| `statistic_id` | `00003`=Mean, `00001`=Max, `00002`=Min, `00011`=Instantaneous |
| `computation_identifier` | `Instantaneous`, `Mean`, `Max`, `Min`, `Median` |
| `computation_period_identifier` | `Points`, `Daily`, `Water Year` |
| `begin_utc` / `end_utc` | Record span in UTC; use `end_utc` to infer if gauge is active |
| `parent_time_series_id` | Null for raw/instantaneous series; derived series point back to parent UUID |
| `hydrologic_unit_code` | 12-digit HUC |
| `state_name` | Full state name |

**Multiplicity:** Results are one row per time-series, not per site. A single gauge has multiple `00060` rows (instantaneous + daily mean, etc.). De-duplicate on `monitoring_location_id` to get a unique site list.

**Active gauge detection:** No `active` flag exists. Filter post-query on `end_utc` being within the last ~30 days.

**Pagination:** This collection uses cursor-based pagination. Follow `links[rel=next].href` in each response (not offset).

**Recommended two-step pattern to find active CO flow gauges:**
1. Query `time-series-metadata?parameter_code=00060&state_name=Colorado` → collect unique `monitoring_location_id` values (filtering `end_utc` to recent dates)
2. Cross-reference against `monitoring-locations` for site metadata (name, drainage area, lat/lon, HUC)

### Individual site lookup

```
GET /collections/monitoring-locations/items/USGS-{site_no}
```

Example:
```
GET /collections/monitoring-locations/items/USGS-09085000
```

## Observations Endpoints

### `latest-continuous` — Most recent reading per time series

```
GET /collections/latest-continuous/items
```

**Key query params:**

| Param | Example | Description |
|-------|---------|-------------|
| `monitoring_location_id` | `USGS-09085000` | USGS- prefix required |
| `parameter_code` | `00060,00010,00065` | Comma-separated codes |
| `f` | `json` | Response format |
| `api_key` | `...` | Your API key |

**Response:** GeoJSON FeatureCollection, one feature per time-series (i.e. one per parameter per site).

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {
        "monitoring_location_id": "USGS-09085000",
        "parameter_code": "00060",
        "time": "2026-03-30T20:00:00+00:00",
        "value": "245.0",
        "unit_of_measure": "ft^3/s"
      }
    }
  ]
}
```

**Usage:** Parse `features` grouped by `parameter_code`; `value` is a string — convert to float.

### `continuous` — Historical / date-range time series

```
GET /collections/continuous/items
```

**Key query params:**

| Param | Example | Description |
|-------|---------|-------------|
| `monitoring_location_id` | `USGS-09085000` | USGS- prefix required |
| `parameter_code` | `00060,00010,00065` | Comma-separated codes |
| `datetime` | `2025-01-01/2025-12-31` or `../P1D` | ISO 8601 interval; `../P1D` means last 24 hours |
| `limit` | `1000` | Max 1000 (default 10) |
| `f` | `json` | Response format |
| `api_key` | `...` | Your API key |

**Response:** GeoJSON FeatureCollection; one feature per observation (flat, not grouped by site or parameter). Paginate by following `links[rel=next].href` (cursor-based; do NOT use offset).

**Usage:** Group features by `properties.time` to reconstruct per-timestamp readings across parameters.

## Field Reference

### `properties` fields

The monitoring-locations endpoint is **metadata only** — no parameter codes or measurements. 42 fields total:

**Identity**

| Field | Description |
|-------|-------------|
| `monitoring_location_number` | Bare USGS gauge ID (e.g. `"09085000"`) — use this to match DB records |
| `id` | Prefixed form: `"USGS-09085000"` |
| `monitoring_location_name` | Human-readable name |
| `agency_code` | e.g. `"USGS"` |
| `agency_name` | e.g. `"U.S. Geological Survey"` |

**Geography**

| Field | Description |
|-------|-------------|
| `state_code` / `state_name` | FIPS code and full name |
| `county_code` / `county_name` | County FIPS and name |
| `country_code` / `country_name` | Country |
| `district_code` | USGS district |
| `minor_civil_division_code` | Sub-county division |
| `hydrologic_unit_code` | HUC8 watershed code |
| `basin_code` | Drainage basin |

**Classification**

| Field | Description |
|-------|-------------|
| `site_type_code` | e.g. `ST`, `GW`, `LK` |
| `site_type` | Full label, e.g. `"Stream"` |

**Elevation**

| Field | Description |
|-------|-------------|
| `altitude` | Elevation in feet |
| `altitude_accuracy` | Accuracy in feet |
| `altitude_method_code` / `altitude_method_name` | How altitude was determined |
| `vertical_datum` / `vertical_datum_name` | Datum (e.g. NAVD88) |

**Horizontal accuracy**

| Field | Description |
|-------|-------------|
| `horizontal_positional_accuracy_code` / `name` | Accuracy classification |
| `horizontal_position_method_code` / `name` | How position was determined |
| `original_horizontal_datum` / `name` | Coordinate datum |

**Hydrologic** (stream sites)

| Field | Description |
|-------|-------------|
| `drainage_area` | Drainage area in sq miles |
| `contributing_drainage_area` | Contributing drainage area in sq miles |
| `time_zone_abbreviation` | e.g. `MST` |
| `uses_daylight_savings` | `Y` or `N` |

**Well-specific** (null for non-GW sites)

| Field | Description |
|-------|-------------|
| `construction_date` | Date well was constructed |
| `aquifer_code` / `national_aquifer_code` | Aquifer identifiers |
| `aquifer_type_code` | Confined, unconfined, etc. |
| `well_constructed_depth` | Depth to bottom of well casing (ft) |
| `hole_constructed_depth` | Total drilled depth (ft) |
| `depth_source_code` | How depth was determined |

**Audit**

| Field | Description |
|-------|-------------|
| `revision_note` | Change notes |
| `revision_created` | Record creation timestamp |
| `revision_modified` | Last modified timestamp |

### geometry

Coordinates are `[longitude, latitude]` (GeoJSON standard — lon first).

```python
lon = feature["geometry"]["coordinates"][0]
lat = feature["geometry"]["coordinates"][1]
```

## Site Type Codes

The full enumeration is available at `/collections/site-types/items`. There are 56 total (16 primary, 42 sub-types).

### Primary types

| Code | Name |
|------|------|
| `AG` | Aggregate groundwater use |
| `AS` | Aggregate surface-water use |
| `AT` | Atmosphere |
| `AW` | Aggregate water-use establishment |
| `ES` | Estuary |
| `GL` | Glacier |
| `GW` | Well |
| `LA` | Land |
| `LK` | Lake, Reservoir, Impoundment |
| `OC` | Ocean |
| `SB` | Subsurface |
| `SP` | Spring |
| `ST` | Stream |
| `WE` | Wetland |

### Stream sub-types

| Code | Name |
|------|------|
| `ST-CA` | Canal |
| `ST-DCH` | Ditch |
| `ST-TS` | Tidal stream |

### Groundwater sub-types

| Code | Name |
|------|------|
| `GW-CR` | Collector or Ranney type well |
| `GW-EX` | Extensometer well |
| `GW-HZ` | Hyporheic-zone well |
| `GW-IW` | Interconnected wells |
| `GW-MW` | Multiple wells |
| `GW-TH` | Test hole not completed as a well |

### Facility sub-types (`FA-*`)

| Code | Name |
|------|------|
| `FA-AWL` | Animal waste lagoon |
| `FA-CI` | Cistern |
| `FA-CS` | Combined sewer |
| `FA-DV` | Diversion |
| `FA-FON` | Field, Pasture, Orchard, or Nursery |
| `FA-GC` | Golf course |
| `FA-HP` | Hydroelectric plant |
| `FA-LF` | Landfill |
| `FA-OF` | Outfall |
| `FA-PV` | Pavement |
| `FA-QC` | Laboratory or sample-preparation area |
| `FA-SEW` | Wastewater sewer |
| `FA-SPS` | Septic system |
| `FA-STS` | Storm sewer |
| `FA-TEP` | Thermoelectric plant |
| `FA-WDS` | Water-distribution system |
| `FA-WIW` | Waste injection well |
| `FA-WTP` | Water-supply treatment plant |
| `FA-WU` | Water-use establishment |
| `FA-WWD` | Wastewater land application |
| `FA-WWTP` | Wastewater-treatment plant |

### Other sub-types

| Code | Name |
|------|------|
| `LA-EX` | Excavation |
| `LA-OU` | Outcrop |
| `LA-PLY` | Playa |
| `LA-SH` | Soil hole |
| `LA-SNK` | Sinkhole |
| `LA-SR` | Shore |
| `LA-VOL` | Volcanic vent |
| `OC-CO` | Coastal |
| `SB-CV` | Cave |
| `SB-GWD` | Groundwater drain |
| `SB-TSM` | Tunnel, shaft, or mine |
| `SB-UZ` | Unsaturated zone |

## Notes & Gotchas

- **State codes are numeric FIPS, not postal abbreviations.** `stateCd=CO` is now `state_code=08`. Using `CO` silently returns no results.
- **No active/inactive filter.** The `siteStatus=active` param from the legacy API doesn't exist here. For Riffle's gauge filtering, cross-reference against `time-series-metadata` or rely on the gauge list already seeded in the DB.
- **GeoJSON lon/lat order.** Coordinates are `[lon, lat]`, not `[lat, lon]`. Easy to mix up.
- **`id` vs `monitoring_location_number`.** The DB stores bare site numbers (e.g. `09085000`). Strip the `USGS-` prefix when matching, or use `monitoring_location_number` directly.
- **Max limit is 10000** per request. For state-wide queries, 1000 is a safe page size.

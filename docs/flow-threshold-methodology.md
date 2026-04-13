# Flow Threshold Methodology

## Overview

Riffle uses per-gauge, per-season flow thresholds to bootstrap condition
labels for the XGBoost training pipeline. These thresholds determine when a
river is labeled Blown Out, Poor, Fair, Good, or Excellent during training.

## Data Source

Thresholds are derived from **2 years of daily mean flow data** (April 2024
through April 2026) stored in the `gauge_readings_daily` table. Each of the
23 active gauges has 250–730 daily observations depending on when the gauge
was added to the system.

## Seasonal Splits

Colorado rivers have dramatically different flow profiles depending on
the time of year. A flow of 1,000 cfs on the Arkansas at Salida is normal
during June runoff but would be extreme in November. To account for this,
thresholds are computed separately for three seasons:

| Season     | Months    | Characteristics                            |
|------------|-----------|---------------------------------------------|
| **Runoff** | Apr–Jul   | Snowmelt-driven high water; widest flow range |
| **Baseflow** | Mar, Aug–Nov | Stable, lower flows; primary fishing season |
| **Winter** | Dec–Feb   | Low flows; ice risk at elevation             |

## Percentile Method

For each gauge and season, we compute three percentiles from the historical
daily mean flow (cfs):

| Threshold      | Percentile | Meaning                                      |
|---------------|------------|-----------------------------------------------|
| `optimal_low`  | **P25**    | 25th percentile — below this is unusually low  |
| `optimal_high` | **P75**    | 75th percentile — above this is elevated flow  |
| `blowout`      | **P95**    | 95th percentile — dangerously high, unfishable |

This means:
- **50% of days** fall in the optimal range (P25–P75) → labeled Good/Excellent
- **20% of days** are between P75 and P95 → labeled Fair or Poor
- **5% of days** exceed P95 → labeled Blown Out
- **25% of days** are below P25 → labeled Fair (unusually low)

### SQL Used

```sql
SELECT g.usgs_gauge_id, g.name,
  CASE
    WHEN EXTRACT(MONTH FROM grd.observed_date) IN (12, 1, 2) THEN 'winter'
    WHEN EXTRACT(MONTH FROM grd.observed_date) IN (4, 5, 6, 7) THEN 'runoff'
    ELSE 'baseflow'
  END AS season,
  round(percentile_cont(0.25) WITHIN GROUP (ORDER BY grd.flow_cfs)::numeric, 0) AS p25,
  round(percentile_cont(0.75) WITHIN GROUP (ORDER BY grd.flow_cfs)::numeric, 0) AS p75,
  round(percentile_cont(0.95) WITHIN GROUP (ORDER BY grd.flow_cfs)::numeric, 0) AS p95
FROM gauge_readings_daily grd
JOIN gauges g ON g.id = grd.gauge_id
WHERE grd.flow_cfs IS NOT NULL
GROUP BY g.usgs_gauge_id, g.name,
  CASE
    WHEN EXTRACT(MONTH FROM grd.observed_date) IN (12, 1, 2) THEN 'winter'
    WHEN EXTRACT(MONTH FROM grd.observed_date) IN (4, 5, 6, 7) THEN 'runoff'
    ELSE 'baseflow'
  END
ORDER BY g.name, season;
```

## Winter and Freezing Gauges

Seven gauges are marked `freezes: True` in the config:

- Above Difficult Creek (Roaring Fork) — tiny creek, 8–9 cfs in winter
- Lawson (Clear Creek) — high-elevation canyon, 20–22 cfs
- Taylor Park (Taylor River) — above reservoir, high elevation
- Golden (Clear Creek) — canyon mouth ices up, 28–37 cfs
- Below Silverton (Animas) — ~9,300 ft elevation
- Steamboat Springs (Yampa) — 40.5°N, northern Colorado
- Maybell (Yampa) — 40.5°N, remote northern Colorado

During Dec–Feb, these gauges are auto-labeled **Poor** regardless of flow
readings, which can be unreliable under ice cover. They do not define
winter thresholds — the label function detects the season and freeze flag
and short-circuits.

Non-freezing gauges (tailwaters, larger rivers, lower elevation) use their
winter thresholds normally during Dec–Feb.

## Label Assignment Logic

The `label_condition()` function in `pipeline/plugins/ml/train.py` applies
thresholds in priority order:

1. If `freezes=True` and month is Dec–Feb → **Poor**
2. If flow > blowout OR water temp > 68°F → **Blown Out**
3. If flow > optimal_high OR water temp ≥ 65°F → **Poor**
4. If flow > blend point (0.85 × optimal_high + 0.15 × optimal_low) OR water temp ≥ 60°F → **Fair**
5. If optimal_low ≤ flow ≤ optimal_high and water temp ≤ 60°F:
   - Water temp ≤ 50°F → **Excellent**
   - Otherwise → **Good**
6. If flow < optimal_low → **Fair**
7. Fallback → **Good**

## Updating Thresholds

As more data accumulates, thresholds should be recomputed periodically.
Re-run the SQL above against the latest `gauge_readings_daily` data and
update `pipeline/config/rivers.py`. The seasonal percentile method is
deterministic and reproducible.

## Computed: 2026-04-12

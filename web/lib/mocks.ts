import type { ForecastDay, RiverDetail, RiverSummary } from "@/config/api";

function isoDate(offsetDays: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

function buildForecast(
  todayCondition: string,
  forecastConditions: string[],
): ForecastDay[] {
  const today: ForecastDay = {
    date: isoDate(0),
    condition: todayCondition,
    confidence: 0.82,
    is_forecast: false,
    precip_mm: 0.0,
    air_temp_f_mean: 64,
    air_temp_f_min: 48,
    air_temp_f_max: 76,
  };
  const upcoming: ForecastDay[] = forecastConditions.map((condition, i) => ({
    date: isoDate(i + 1),
    condition,
    confidence: 0.65 - i * 0.05,
    is_forecast: true,
    precip_mm: i === 2 ? 8.4 : i === 5 ? null : 1.2 + i * 0.3,
    air_temp_f_mean: 70 - i * 2,
    air_temp_f_min: 54 - i * 2,
    air_temp_f_max: 82 - i * 2,
  }));
  return [today, ...upcoming];
}

const RIVERS: Array<{
  summary: RiverSummary;
  current: RiverDetail["current"];
  forecast: ForecastDay[];
}> = [
  {
    summary: {
      gauge_id: "07091200",
      name: "Salida",
      river: "Arkansas River",
      lat: 38.5347,
      lon: -106.0008,
      condition: "Excellent",
      confidence: 0.88,
    },
    current: {
      flow_cfs: 512,
      water_temp_f: 54.2,
      gauge_height_ft: 3.41,
      fetched_at: new Date().toISOString(),
    },
    forecast: buildForecast("Excellent", [
      "Excellent",
      "Good",
      "Good",
      "Fair",
      "Good",
      "Good",
      "Excellent",
    ]),
  },
  {
    summary: {
      gauge_id: "09085000",
      name: "Glenwood Springs",
      river: "Roaring Fork River",
      lat: 39.5486,
      lon: -107.3247,
      condition: "Good",
      confidence: 0.79,
    },
    current: {
      flow_cfs: 1140,
      water_temp_f: 51.6,
      gauge_height_ft: 4.92,
      fetched_at: new Date().toISOString(),
    },
    forecast: buildForecast("Good", [
      "Good",
      "Good",
      "Fair",
      "Fair",
      "Poor",
      "Fair",
      "Good",
    ]),
  },
  {
    summary: {
      gauge_id: "09057500",
      name: "Silverthorne",
      river: "Blue River",
      lat: 39.6328,
      lon: -106.0694,
      condition: "Fair",
      confidence: 0.71,
    },
    current: {
      flow_cfs: 248,
      water_temp_f: 47.9,
      gauge_height_ft: 2.18,
      fetched_at: new Date().toISOString(),
    },
    forecast: buildForecast("Fair", [
      "Fair",
      "Fair",
      "Poor",
      "Poor",
      "Fair",
      "Good",
      "Good",
    ]),
  },
  {
    summary: {
      gauge_id: "06700000",
      name: "Above Cheesman Lake",
      river: "South Platte",
      lat: 39.1628,
      lon: -105.3097,
      condition: "Poor",
      confidence: 0.74,
    },
    current: {
      flow_cfs: 612,
      water_temp_f: 56.1,
      gauge_height_ft: 5.04,
      fetched_at: new Date().toISOString(),
    },
    forecast: buildForecast("Poor", [
      "Poor",
      "Poor",
      "Blown Out",
      "Blown Out",
      "Poor",
      "Fair",
      "Fair",
    ]),
  },
  {
    summary: {
      gauge_id: "09058000",
      name: "Kremmling",
      river: "Colorado River",
      lat: 40.0367,
      lon: -106.4400,
      condition: "Blown Out",
      confidence: 0.91,
    },
    current: {
      flow_cfs: 4520,
      water_temp_f: 49.8,
      gauge_height_ft: 8.71,
      fetched_at: new Date().toISOString(),
    },
    forecast: buildForecast("Blown Out", [
      "Blown Out",
      "Blown Out",
      "Poor",
      "Poor",
      "Fair",
      "Fair",
      "Good",
    ]),
  },
  {
    summary: {
      gauge_id: "06716500",
      name: "Lawson",
      river: "Clear Creek",
      lat: 39.7658,
      lon: -105.6261,
      condition: null,
      confidence: null,
    },
    current: null,
    forecast: [],
  },
];

export function mockRiversList(): RiverSummary[] {
  return RIVERS.map((r) => r.summary);
}

export function mockRiverDetail(gaugeId: string): RiverDetail | null {
  const found = RIVERS.find((r) => r.summary.gauge_id === gaugeId);
  if (!found) return null;
  return {
    gauge_id: found.summary.gauge_id,
    name: found.summary.name,
    river: found.summary.river,
    lat: found.summary.lat,
    lon: found.summary.lon,
    current: found.current,
    forecast: found.forecast,
    usgs_url: `https://waterdata.usgs.gov/monitoring-location/${found.summary.gauge_id}/`,
  };
}

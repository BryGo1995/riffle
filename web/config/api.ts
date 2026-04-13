const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface RiverSummary {
  gauge_id: string;
  name: string;
  river: string;
  lat: number;
  lon: number;
  condition: string | null;
  confidence: number | null;
}

export interface ForecastDay {
  date: string;
  condition: string;
  confidence: number;
  is_forecast: boolean;
  precip_mm: number | null;
  air_temp_f: number | null;
}

export interface RiverDetail {
  gauge_id: string;
  name: string;
  river: string;
  lat: number;
  lon: number;
  current: {
    flow_cfs: number | null;
    water_temp_f: number | null;
    gauge_height_ft: number | null;
    fetched_at: string;
  } | null;
  forecast: ForecastDay[];
  usgs_url: string;
}


export async function fetchRivers(): Promise<RiverSummary[]> {
  const res = await fetch(`${BASE_URL}/api/v1/rivers`, { next: { revalidate: 3600 } });
  if (!res.ok) throw new Error("Failed to fetch rivers");
  return res.json();
}

export async function fetchRiver(gaugeId: string): Promise<RiverDetail> {
  const res = await fetch(`${BASE_URL}/api/v1/rivers/${gaugeId}`, {
    next: { revalidate: 3600 },
  });
  if (!res.ok) throw new Error(`Failed to fetch river ${gaugeId}`);
  return res.json();
}


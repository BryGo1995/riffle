import Link from "next/link";
import { notFound } from "next/navigation";
import { fetchRiver, fetchRiverHistory } from "@/config/api";
import type { RiverDetail, RiverHistory } from "@/config/api";
import ConditionBadge from "@/components/ConditionBadge";
import ForecastStrip from "@/components/ForecastStrip";
import HistoryChart from "@/components/HistoryChart";

export const revalidate = 3600;

interface Props {
  params: { id: string };
}

export default async function RiverDetailPage({ params }: Props) {
  let river: RiverDetail, historyData: RiverHistory;
  try {
    [river, historyData] = await Promise.all([
      fetchRiver(params.id),
      fetchRiverHistory(params.id),
    ]);
  } catch {
    notFound();
  }

  const today = river.forecast.find((d) => !d.is_forecast);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-slate-900 text-white px-6 py-3 flex items-center gap-4">
        <Link href="/" className="text-slate-400 hover:text-white text-sm">
          ← Map
        </Link>
        <div>
          <h1 className="text-xl font-bold">{river.name}</h1>
          <p className="text-slate-400 text-sm">{river.river}</p>
        </div>
      </header>

      <main className="max-w-2xl mx-auto px-6 py-8 space-y-8">
        {/* Current condition */}
        <section className="bg-white rounded-xl shadow-sm p-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Today's Conditions
          </h2>
          <div className="flex items-center gap-4 mb-4">
            <ConditionBadge condition={today?.condition ?? null} />
          </div>
          {river.current && (
            <div className="grid grid-cols-3 gap-4 text-center">
              <div>
                <p className="text-2xl font-bold text-gray-800">
                  {river.current.flow_cfs?.toFixed(0) ?? "—"}
                </p>
                <p className="text-xs text-gray-500">cfs</p>
              </div>
              <div>
                <p className="text-2xl font-bold text-gray-800">
                  {river.current.water_temp_f?.toFixed(1) ?? "—"}°
                </p>
                <p className="text-xs text-gray-500">water temp (°F)</p>
              </div>
              <div>
                <p className="text-2xl font-bold text-gray-800">
                  {river.current.gauge_height_ft?.toFixed(2) ?? "—"}
                </p>
                <p className="text-xs text-gray-500">gauge height (ft)</p>
              </div>
            </div>
          )}
          <a
            href={river.usgs_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-4 inline-block text-xs text-blue-600 hover:underline"
          >
            View raw USGS gauge data →
          </a>
        </section>

        {/* 3-day forecast */}
        <section className="bg-white rounded-xl shadow-sm p-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
            3-Day Forecast
          </h2>
          <p className="text-xs text-gray-400 mb-3">
            Forecast days marked "est." use predicted weather with current flow as a baseline.
          </p>
          <ForecastStrip forecast={river.forecast} />
        </section>

        {/* 30-day history */}
        <section className="bg-white rounded-xl shadow-sm p-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">
            30-Day Condition History
          </h2>
          <HistoryChart history={historyData.history} />
        </section>
      </main>
    </div>
  );
}

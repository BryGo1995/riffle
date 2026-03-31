import { Suspense } from "react";
import { fetchRivers } from "@/config/api";
import RiverMap from "@/components/RiverMap";

export const revalidate = 3600;

export default async function HomePage() {
  const rivers = await fetchRivers();

  return (
    <main className="flex flex-col h-screen">
      <header className="px-6 py-3 bg-slate-900 text-white flex items-center gap-3 shrink-0">
        <h1 className="text-xl font-bold tracking-tight">Riffle</h1>
        <span className="text-slate-400 text-sm">Colorado Fly Fishing Conditions</span>
      </header>

      {/* Legend */}
      <div className="flex gap-3 px-6 py-2 bg-slate-800 text-white text-xs shrink-0 flex-wrap">
        {[
          { label: "Excellent", color: "#1a6b1a" },
          { label: "Good", color: "#22c55e" },
          { label: "Fair", color: "#eab308" },
          { label: "Poor", color: "#f97316" },
          { label: "Blown Out", color: "#dc2626" },
        ].map(({ label, color }) => (
          <div key={label} className="flex items-center gap-1">
            <span
              className="inline-block w-3 h-3 rounded-full border border-white"
              style={{ backgroundColor: color }}
            />
            <span>{label}</span>
          </div>
        ))}
      </div>

      {/* Map */}
      <div className="flex-1 relative">
        <Suspense fallback={<div className="w-full h-full bg-slate-100 animate-pulse" />}>
          <RiverMap rivers={rivers} />
        </Suspense>
      </div>

      <footer className="px-6 py-2 bg-slate-900 text-slate-500 text-xs shrink-0">
        Data: USGS Water Services + Open-Meteo · Updated daily · Click a marker for details
      </footer>
    </main>
  );
}

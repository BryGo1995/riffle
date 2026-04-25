import ConditionBadge from "./ConditionBadge";
import type { ForecastDay } from "@/config/api";

interface ForecastStripProps {
  forecast: ForecastDay[];
}

function formatDate(dateStr: string): string {
  return new Date(dateStr + "T12:00:00").toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

export default function ForecastStrip({ forecast }: ForecastStripProps) {
  return (
    <div className="flex gap-3 overflow-x-auto pb-2">
      {forecast.map((day) => (
        <div
          key={day.date}
          className="flex-shrink-0 w-36 rounded-lg border border-gray-200 bg-white p-3 shadow-sm"
        >
          <p className="text-xs text-gray-500 mb-1">{formatDate(day.date)}</p>
          <ConditionBadge condition={day.condition} estimated={day.is_forecast} />
          {day.precip_mm !== null && (
            <p className="text-xs text-gray-600 mt-2">
              Precip: {day.precip_mm.toFixed(1)} mm
            </p>
          )}
          {day.air_temp_f_mean !== null && (
            <p className="text-xs text-gray-600">
              Air: {Math.round(day.air_temp_f_mean)}°F
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

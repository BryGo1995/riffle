"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { HistoryDay } from "@/config/api";

const CONDITION_ORDER = ["Blown Out", "Poor", "Fair", "Good", "Excellent"];

interface HistoryChartProps {
  history: HistoryDay[];
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + "T12:00:00");
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export default function HistoryChart({ history }: HistoryChartProps) {
  const data = [...history].reverse().map((day) => ({
    date: formatDate(day.date),
    score: CONDITION_ORDER.indexOf(day.condition),
    condition: day.condition,
    flow_cfs: day.flow_cfs,
  }));

  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
        <XAxis dataKey="date" tick={{ fontSize: 11 }} interval={4} />
        <YAxis
          domain={[0, 4]}
          tickFormatter={(v) => CONDITION_ORDER[v]?.split(" ")[0] ?? ""}
          tick={{ fontSize: 11 }}
          width={55}
        />
        <Tooltip
          formatter={(_value: unknown, _name: unknown, props: any) => [
            props.payload.condition,
            "Condition",
          ]}
        />
        <Line
          type="monotone"
          dataKey="score"
          stroke="#16a34a"
          strokeWidth={2}
          dot={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

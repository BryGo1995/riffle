const CONDITION_STYLES: Record<string, string> = {
  Excellent: "bg-green-800 text-white",
  Good: "bg-green-500 text-white",
  Fair: "bg-yellow-400 text-gray-900",
  Poor: "bg-orange-500 text-white",
  "Blown Out": "bg-red-600 text-white",
};

interface ConditionBadgeProps {
  condition: string | null;
  estimated?: boolean;
}

export default function ConditionBadge({ condition, estimated }: ConditionBadgeProps) {
  if (!condition) {
    return (
      <span className="inline-block px-2 py-1 rounded text-sm bg-gray-200 text-gray-500">
        No data
      </span>
    );
  }
  const style = CONDITION_STYLES[condition] ?? "bg-gray-400 text-white";
  return (
    <span className={`inline-block px-2 py-1 rounded text-sm font-semibold ${style}`}>
      {condition}
      {estimated && (
        <span className="ml-1 text-xs font-normal opacity-75">(est.)</span>
      )}
    </span>
  );
}

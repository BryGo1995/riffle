"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import type { RiverSummary } from "@/config/api";

const CONDITION_COLORS: Record<string, string> = {
  Excellent: "#1a6b1a",
  Good: "#22c55e",
  Fair: "#eab308",
  Poor: "#f97316",
  "Blown Out": "#dc2626",
};

interface RiverMapProps {
  rivers: RiverSummary[];
}

export default function RiverMap({ rivers }: RiverMapProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    if (!mapRef.current) return;

    // Leaflet must be imported dynamically (no SSR)
    import("leaflet").then((L) => {
      // Avoid re-initializing if map already mounted
      if ((mapRef.current as HTMLDivElement & { _leaflet_id?: number })._leaflet_id) return;

      const map = L.map(mapRef.current!, {
        center: [39.0, -105.5],
        zoom: 7,
      });

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "© OpenStreetMap contributors",
      }).addTo(map);

      rivers.forEach((river) => {
        const color = river.condition
          ? (CONDITION_COLORS[river.condition] ?? "#6b7280")
          : "#6b7280";

        const marker = L.circleMarker([river.lat, river.lon], {
          radius: 10,
          fillColor: color,
          color: "#fff",
          weight: 2,
          fillOpacity: 0.9,
        }).addTo(map);

        marker.bindPopup(
          `<b>${river.name}</b><br>${river.river}<br>${river.condition ?? "No data"}`
        );

        marker.on("click", () => {
          router.push(`/rivers/${river.gauge_id}`);
        });
      });
    });
  }, [rivers, router]);

  return <div ref={mapRef} className="w-full h-full" />;
}

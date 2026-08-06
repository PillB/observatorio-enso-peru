import { NextResponse } from "next/server";
import { buildCurrentStatus, buildQualitySummary } from "@/lib/enso/derived";
import { SOURCES } from "@/lib/enso/sources";
import { INDICATORS } from "@/lib/enso/methodology";

export const runtime = "nodejs";

// Estado actual consolidado + manifiesto de fuentes y calidad.

export async function GET() {
  const status = buildCurrentStatus();
  const quality = buildQualitySummary();
  return NextResponse.json({
    status,
    quality,
    sources: SOURCES,
    indicators: INDICATORS,
    manifest: {
      name: "Observatorio ENSO Perú",
      dataVersion: "1.0.0",
      generatedAt: new Date().toISOString(),
      coverage: "1990-01 .. 2026-07 (mensual)",
    },
  });
}

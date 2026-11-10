import { useMemo, useState } from "react";
import { CartesianGrid, ComposedChart, Legend, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Series } from "../api/types";
import { Segmented } from "./ui";

export function ResultsChart({ series, peak, saturated, rangeG = 16 }: { series: Series; peak: number | null; saturated: boolean; rangeG?: number }) {
  const [view, setView] = useState<"impact" | "full">("impact");
  const [axes, setAxes] = useState(false);
  const [filtered, setFiltered] = useState(false);
  const data = useMemo(
    () =>
      series.t_ms.map((t, i) => ({
        t,
        mag: series.mag[i],
        ax: series.ax[i],
        ay: series.ay[i],
        az: series.az[i],
        f: series.mag_filtered[i],
      })),
    [series],
  );
  const m = series.markers;
  const domain: [number, number] | ["dataMin", "dataMax"] =
    view === "full" || m.peak_ms == null
      ? ["dataMin", "dataMax"]
      : [Math.max(series.t_ms[0] ?? -300, Math.min(-120, (m.freefall_start_ms ?? -150) - 40)), Math.min(series.t_ms[series.t_ms.length - 1] ?? 600, 450)];
  // Scale to the data, not to the sensor range: |a| combines three axes, so
  // it can read above the per-axis limit (up to √3 × range when all clip).
  const dataMax = useMemo(() => {
    let mag = 0;
    let axis = 0;
    for (let i = 0; i < series.mag.length; i++) {
      const v = series.mag[i];
      if (v != null && v > mag) mag = v;
      for (const a of [series.ax[i], series.ay[i], series.az[i]]) if (a != null && Math.abs(a) > axis) axis = Math.abs(a);
    }
    return { mag, axis };
  }, [series]);
  const top = Math.max(peak ?? 0, dataMax.mag, axes ? dataMax.axis : 0, saturated && axes ? rangeG : 0, 3.5);
  const maxY = Math.ceil((top * 1.1) / 2) * 2;
  const minY = axes ? -Math.max(2, Math.ceil((dataMax.axis * 1.1) / 2) * 2) : 0;

  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <Segmented
          size="sm"
          value={view}
          onChange={setView}
          options={[
            { value: "impact", label: "Zoom: impact" },
            { value: "full", label: "Full capture" },
          ]}
        />
        <div className="flex gap-2">
          <button type="button" onClick={() => setAxes((v) => !v)} className={`rounded-lg px-2.5 py-1 text-xs font-semibold ${axes ? "bg-telemetry text-space-950" : "bg-space-700 text-slate-300"}`}>
            X / Y / Z axes
          </button>
          <button type="button" onClick={() => setFiltered((v) => !v)} className={`rounded-lg px-2.5 py-1 text-xs font-semibold ${filtered ? "bg-telemetry text-space-950" : "bg-space-700 text-slate-300"}`} title={series.filter_method}>
            Smoothed (display only)
          </button>
        </div>
      </div>
      <div className="min-h-[240px] flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 10, right: 20, bottom: 18, left: 0 }}>
            <CartesianGrid stroke="rgba(34,211,238,0.08)" />
            <XAxis
              dataKey="t"
              type="number"
              domain={domain}
              allowDataOverflow
              tick={{ fill: "#94a3b8", fontSize: 12 }}
              tickFormatter={(v: number) => `${Math.round(v)}`}
              label={{ value: series.time_zero === "peak" ? "time from peak (ms)" : "time (ms)", position: "insideBottom", offset: -8, fill: "#64748b", fontSize: 12 }}
            />
            <YAxis domain={[minY, maxY]} allowDataOverflow tick={{ fill: "#94a3b8", fontSize: 12 }} tickFormatter={(v: number) => `${v} g`} width={56} />
            <Tooltip
              contentStyle={{ background: "#081127", border: "1px solid rgba(34,211,238,0.3)", borderRadius: 12 }}
              labelFormatter={(v) => `${Number(v).toFixed(1)} ms`}
              formatter={(v) => (typeof v === "number" ? `${v.toFixed(2)} g` : String(v))}
            />
            {m.freefall_start_ms != null && m.freefall_end_ms != null && (
              <ReferenceArea x1={m.freefall_start_ms} x2={m.freefall_end_ms} fill="#3b82f6" fillOpacity={0.12} label={{ value: "free fall", fill: "#93c5fd", fontSize: 12, position: "insideTop" }} />
            )}
            {m.impact_start_ms != null && m.impact_end_ms != null && (
              <ReferenceArea x1={m.impact_start_ms} x2={m.impact_end_ms} fill="#f97316" fillOpacity={0.1} />
            )}
            <ReferenceLine y={1} stroke="#64748b" strokeDasharray="4 4" label={{ value: "1 g (at rest)", fill: "#64748b", fontSize: 11, position: "insideBottomRight" }} />
            {/* The sensor limit applies to each axis, not to |a|: show it only with the X/Y/Z traces. */}
            {saturated && axes && (
              <ReferenceLine y={rangeG} stroke="#ef4444" strokeDasharray="6 4" label={{ value: `per-axis limit ±${rangeG} g`, fill: "#fca5a5", fontSize: 12, position: "insideTopRight" }} />
            )}
            {saturated && axes && <ReferenceLine y={-rangeG} stroke="#ef4444" strokeDasharray="6 4" />}
            {!saturated && peak != null && m.peak_ms != null && <ReferenceLine x={m.peak_ms} stroke="#f97316" strokeDasharray="3 3" />}
            {(m.rebounds_ms ?? []).map((r, i) => (r != null ? <ReferenceLine key={i} x={r} stroke="#f59e0b" strokeDasharray="2 4" label={{ value: "rebound", fill: "#fcd34d", fontSize: 11, position: "top" }} /> : null))}
            {axes && <Line dataKey="ax" name="X" stroke="#f472b6" dot={false} strokeWidth={1.2} isAnimationActive={false} connectNulls={false} />}
            {axes && <Line dataKey="ay" name="Y" stroke="#a3e635" dot={false} strokeWidth={1.2} isAnimationActive={false} connectNulls={false} />}
            {axes && <Line dataKey="az" name="Z" stroke="#60a5fa" dot={false} strokeWidth={1.2} isAnimationActive={false} connectNulls={false} />}
            <Line dataKey="mag" name="|a| raw" stroke="#22d3ee" dot={false} strokeWidth={2.4} isAnimationActive={false} connectNulls={false} />
            {filtered && <Line dataKey="f" name="|a| smoothed" stroke="#e2e8f0" strokeDasharray="5 3" dot={false} strokeWidth={1.5} isAnimationActive={false} />}
            <Legend verticalAlign="top" height={24} wrapperStyle={{ fontSize: 12, color: "#cbd5e1" }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1 text-[11px] text-slate-500">
        {series.decimated ? `Showing ${series.points} of ${series.n} samples (${series.decimation}). ` : `All ${series.n} samples shown. `}
        Raw values are unfiltered; peaks are computed from raw data.{filtered ? ` Smoothing: ${series.filter_method}.` : ""}
      </div>
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ErrorBar, LabelList, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { api } from "../api/client";
import type { Comparison as Cmp, DataOrigin, SessionInfo } from "../api/types";
import { Badge, Button, Panel, Segmented } from "../components/ui";
import { fmtG, fmtHeight, fmtTime } from "../lib/format";
import { useStore } from "../state/store";

type GroupBy = "configuration" | "height" | "session" | "date";

export function Comparison() {
  const settings = useStore((s) => s.settings);
  const dataVersion = useStore((s) => s.dataVersion);
  const sensor = useStore((s) => s.sensor);
  const go = useStore((s) => s.go);
  const newMission = useStore((s) => s.newMission);
  const [origin, setOrigin] = useState<DataOrigin>(sensor?.data_origin === "physical" ? "physical" : "simulated");
  const [height, setHeight] = useState<number | null>(settings?.drop_height_m ?? null);
  const [groupBy, setGroupBy] = useState<GroupBy>("configuration");
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [data, setData] = useState<Cmp | null>(null);

  useEffect(() => {
    api.sessions().then(setSessions).catch(() => undefined);
  }, [dataVersion]);

  useEffect(() => {
    api
      .comparison({ data_origin: origin, drop_height_m: groupBy === "height" ? null : height, group_by: groupBy, session_id: sessionId })
      .then(setData)
      .catch(() => setData(null));
  }, [origin, height, groupBy, sessionId, dataVersion]);

  const bars = useMemo(
    () =>
      (data?.groups ?? []).map((g) => ({
        key: `${g.configuration_code}${g.group ? ` · ${g.group}` : ""}`,
        name: g.configuration_name,
        mean: g.mean_peak_g !== null ? Number(g.mean_peak_g.toFixed(2)) : null,
        err: g.mean_peak_g !== null && g.min_peak_g !== null && g.max_peak_g !== null ? [g.mean_peak_g - g.min_peak_g, g.max_peak_g - g.mean_peak_g] : [0, 0],
        color: g.color === "#f8fafc" ? "#e2e8f0" : g.color,
        g,
      })),
    [data],
  );
  const best = data?.ranking[0];
  const bestGroup = data?.groups.find((g) => g.configuration_code === best?.configuration_code && g.group === best?.group);
  const points = (data?.points ?? []).map((p) => ({ ...p, x: new Date(p.timestamp).getTime(), y: p.measured_peak_g }));
  const colorFor = (code: string) => data?.groups.find((g) => g.configuration_code === code)?.color ?? "#22d3ee";

  return (
    <div className="flex min-h-full flex-col gap-4 p-5 xl:h-full">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="font-display text-sm tracking-[0.35em] text-mars">MISSION COMPARISON</div>
          <h1 className="font-display text-3xl font-black text-white">Which landing gear protects the payload best?</h1>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Segmented
            value={origin}
            onChange={setOrigin}
            options={[
              { value: "physical", label: "Measured" },
              { value: "simulated", label: "Simulated" },
              { value: "unverified", label: "Imported" },
            ]}
          />
          <Segmented
            value={groupBy}
            onChange={setGroupBy}
            options={[
              { value: "configuration", label: "By gear" },
              { value: "height", label: "By height" },
              { value: "session", label: "By session" },
              { value: "date", label: "By date" },
            ]}
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {groupBy !== "height" && (
          <>
            <span className="text-xs font-semibold uppercase tracking-widest text-slate-400">Drop height</span>
            {(data?.heights_available_m ?? []).map((h) => (
              <Button key={h} size="sm" variant={height !== null && Math.abs(h - height) < 0.005 ? "primary" : "ghost"} onClick={() => setHeight(h)}>
                {fmtHeight(h)}
              </Button>
            ))}
            <Button size="sm" variant={height === null ? "primary" : "ghost"} onClick={() => setHeight(null)}>
              All heights
            </Button>
          </>
        )}
        <span className="ml-4 text-xs font-semibold uppercase tracking-widest text-slate-400">Session</span>
        <select
          className="rounded-lg border border-telemetry/20 bg-space-850 px-2 py-1 text-sm"
          value={sessionId ?? ""}
          onChange={(e) => setSessionId(e.target.value ? Number(e.target.value) : null)}
        >
          <option value="">All sessions</option>
          {sessions.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} ({s.test_count})
            </option>
          ))}
        </select>
      </div>

      {origin === "simulated" && <div className="sim-stripes rounded-lg py-1 text-center font-display text-[11px] font-bold tracking-[0.25em] text-purple-100">SIMULATED DATA — NOT PHYSICAL MEASUREMENTS</div>}
      {origin === "unverified" && <div className="rounded-lg bg-caution/15 py-1 text-center font-display text-[11px] font-bold tracking-[0.25em] text-amber-200">IMPORTED DATA — PROVENANCE NOT VERIFIED (NOT RANKED WITH MEASUREMENTS)</div>}
      {height === null && groupBy !== "height" && (data?.heights_available_m.length ?? 0) > 1 && (
        <div className="rounded-lg bg-caution/10 px-3 py-1.5 text-sm text-amber-200">Different drop heights are mixed together — pick one height for a fair comparison.</div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 xl:grid-cols-[1.5fr_1fr]">
        <Panel title="Average peak acceleration (lower is gentler)" className="flex min-h-[340px] flex-col">
          {bars.some((b) => b.mean !== null) ? (
            <div className="min-h-[280px] flex-1">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={bars} margin={{ top: 24, right: 20, left: 0, bottom: 10 }}>
                  <CartesianGrid stroke="rgba(34,211,238,0.08)" vertical={false} />
                  <XAxis dataKey="key" tick={{ fill: "#e2e8f0", fontSize: 14, fontWeight: 600 }} />
                  <YAxis tick={{ fill: "#94a3b8", fontSize: 12 }} tickFormatter={(v: number) => `${v} g`} />
                  <Tooltip
                    contentStyle={{ background: "#081127", border: "1px solid rgba(34,211,238,0.3)", borderRadius: 12 }}
                    formatter={(v) => (typeof v === "number" ? `${v.toFixed(2)} g` : String(v))}
                  />
                  <Bar dataKey="mean" name="Average peak" radius={[8, 8, 0, 0]} maxBarSize={140} isAnimationActive={false}>
                    {bars.map((b) => (
                      <Cell key={b.key} fill={b.color} />
                    ))}
                    <ErrorBar dataKey="err" width={10} stroke="#cbd5e1" strokeWidth={1.5} />
                    <LabelList dataKey="mean" position="top" fill="#f8fafc" fontSize={14} fontWeight={700} formatter={(v) => (v == null ? "" : `${v} g`)} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="flex flex-1 items-center justify-center text-slate-400">No valid {origin === "physical" ? "measured" : origin} landings yet. Run a test!</div>
          )}
          <div className="mt-1 text-[11px] text-slate-500">Bars show the mean of valid tests; whiskers show the lowest and highest. {data?.note}</div>
        </Panel>

        <div className="flex flex-col gap-4 [&>*]:shrink-0 xl:min-h-0 xl:overflow-auto">
          {best && bestGroup && (
            <div className="panel border-go/40 p-4">
              <div className="panel-title text-green-300">Softest landing so far</div>
              <div className="mt-1 flex items-center gap-3">
                <div className="flex h-14 w-14 items-center justify-center rounded-xl font-display text-2xl font-black text-space-950" style={{ background: bestGroup.color }}>
                  {best.configuration_code}
                </div>
                <div>
                  <div className="text-2xl font-bold text-white">{bestGroup.configuration_name}</div>
                  <div className="font-mono text-green-300">{fmtG(best.mean_peak_g, 2)} average · {best.valid} test{best.valid === 1 ? "" : "s"}</div>
                </div>
              </div>
            </div>
          )}
          <Panel title="Test counts">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wider text-slate-400">
                <tr>
                  <th className="py-1">Gear</th>
                  <th className="text-right">Tests</th>
                  <th className="text-right">Valid</th>
                  <th className="text-right">Over range</th>
                  <th className="text-right">Invalid</th>
                  <th className="text-right">Best</th>
                </tr>
              </thead>
              <tbody>
                {(data?.groups ?? []).map((g) => (
                  <tr key={g.configuration_code + g.group} className="border-t border-space-700">
                    <td className="py-1.5">
                      <span className="mr-2 inline-block h-3 w-3 rounded-sm" style={{ background: g.color }} />
                      {g.configuration_code} {g.configuration_name} {g.group && <span className="text-slate-500">· {g.group}</span>}
                    </td>
                    <td className="text-right font-mono">{g.total}</td>
                    <td className="text-right font-mono text-green-300">{g.valid}</td>
                    <td className="text-right font-mono text-red-300">{g.saturated || ""}</td>
                    <td className="text-right font-mono text-slate-400">{g.invalid - g.saturated || ""}</td>
                    <td className="text-right font-mono">{fmtG(g.min_peak_g)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-2 text-[11px] text-slate-500">
              Over-range and invalid tests are counted but never ranked. <Badge tone="muted">{origin}</Badge>
            </div>
          </Panel>
          <Panel title="Every valid landing" className="min-h-[220px]">
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 10, right: 10, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="rgba(34,211,238,0.08)" />
                  <XAxis dataKey="x" type="number" domain={["dataMin", "dataMax"]} tickFormatter={(v: number) => fmtTime(new Date(v).toISOString())} tick={{ fill: "#94a3b8", fontSize: 11 }} />
                  <YAxis dataKey="y" tick={{ fill: "#94a3b8", fontSize: 11 }} tickFormatter={(v: number) => `${v} g`} width={44} />
                  <ZAxis range={[60, 60]} />
                  <Tooltip
                    contentStyle={{ background: "#081127", border: "1px solid rgba(34,211,238,0.3)", borderRadius: 12 }}
                    formatter={(v, n) => (n === "y" ? `${Number(v).toFixed(2)} g` : fmtTime(new Date(Number(v)).toISOString()))}
                  />
                  <Scatter data={points} isAnimationActive={false}>
                    {points.map((p) => (
                      <Cell key={p.id} fill={colorFor(p.configuration_code)} />
                    ))}
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          </Panel>
        </div>
      </div>

      <div className="flex justify-end gap-3">
        <Button variant="mars" size="lg" onClick={() => go("design")}>
          Try another design ▶
        </Button>
        <Button variant="ghost" size="lg" onClick={newMission}>
          New mission
        </Button>
      </div>
    </div>
  );
}

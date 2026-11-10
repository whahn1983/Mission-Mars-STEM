import { useEffect, useState } from "react";
import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { api, ApiError } from "../api/client";
import type { Comparison, Series, TestDetail } from "../api/types";
import { ResultsChart } from "../components/ResultsChart";
import { Badge, Button, Panel, Stat } from "../components/ui";
import { fmtG, fmtHeight, fmtMass, fmtNum, ORIGIN_LABEL, SOURCE_LABEL } from "../lib/format";
import { describePrediction, measuredCategory, predictionVerdict } from "../lib/predict";
import { useStore } from "../state/store";

/** "the Z axis" / "the X and Z axes" from per-axis saturation counts. */
function clippedAxes(counts: Record<string, number> | undefined): string {
  const axes = Object.entries(counts ?? {})
    .filter(([, n]) => n > 0)
    .map(([k]) => k.toUpperCase());
  if (axes.length === 0) return "at least one axis";
  if (axes.length === 1) return `the ${axes[0]} axis`;
  return `the ${axes.slice(0, -1).join(", ")} and ${axes[axes.length - 1]} axes`;
}

function useCountUp(target: number | null, ms = 1200) {
  const [v, setV] = useState(0);
  useEffect(() => {
    if (target === null) return;
    let raf = 0;
    const t0 = performance.now();
    const step = (now: number) => {
      const p = Math.min(1, (now - t0) / ms);
      setV(target * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}

const OUTCOME = {
  success: { emoji: "🎉", label: "Successful landing!", tone: "go" as const, cls: "border-go/60 bg-go/10 text-green-200" },
  needs_improvement: { emoji: "🔧", label: "Needs improvement", tone: "caution" as const, cls: "border-caution/60 bg-caution/10 text-amber-200" },
  invalid: { emoji: "🔁", label: "Invalid test — try again", tone: "alert" as const, cls: "border-alert/60 bg-alert/10 text-red-200" },
};

function OperatorStrip({ test, onChange }: { test: TestDetail; onChange: (t: TestDetail) => void }) {
  const notify = useStore((s) => s.notify);
  const set = async (changes: Partial<TestDetail>) => {
    try {
      onChange(await api.updateTest(test.id, changes));
    } catch (e) {
      notify("error", e instanceof ApiError ? e.message : "Update failed");
    }
  };
  const yn = (key: "landing_stable" | "payload_retained", label: string) => (
    <div className="flex items-center gap-2">
      <span className="text-sm text-slate-300">{label}</span>
      {[true, false].map((v) => (
        <button
          key={String(v)}
          type="button"
          onClick={() => set({ [key]: test[key] === v ? null : v })}
          className={`rounded-lg px-3 py-1 text-sm font-semibold ${test[key] === v ? (v ? "bg-go text-space-950" : "bg-alert text-white") : "bg-space-700 text-slate-300"}`}
        >
          {v ? "Yes" : "No"}
        </button>
      ))}
    </div>
  );
  return (
    <div className="flex flex-wrap items-center gap-4 rounded-xl border border-caution/30 bg-caution/5 px-4 py-2">
      <span className="font-display text-[11px] tracking-widest text-amber-300">OPERATOR</span>
      {yn("landing_stable", "Landed upright?")}
      {yn("payload_retained", "Payload stayed in place?")}
      <button
        type="button"
        onClick={() => set({ excluded: !test.excluded, exclude_reason: test.excluded ? null : "excluded by operator" })}
        className={`rounded-lg px-3 py-1 text-sm font-semibold ${test.excluded ? "bg-alert text-white" : "bg-space-700 text-slate-300"}`}
      >
        {test.excluded ? "Excluded from rankings" : "Exclude from rankings"}
      </button>
    </div>
  );
}

export function Results() {
  const testId = useStore((s) => s.resultTestId);
  const gradeBand = useStore((s) => s.gradeBand);
  const operatorUnlocked = useStore((s) => s.operatorUnlocked);
  const go = useStore((s) => s.go);
  const newMission = useStore((s) => s.newMission);
  const dataVersion = useStore((s) => s.dataVersion);
  const [test, setTest] = useState<TestDetail | null>(null);
  const [series, setSeries] = useState<Series | null>(null);
  const [cmp, setCmp] = useState<Comparison | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!testId) return;
    let alive = true;
    Promise.all([api.test(testId), api.series(testId)])
      .then(([t, s]) => {
        if (!alive) return;
        setTest(t);
        setSeries(s);
        return api.comparison({ data_origin: t.data_origin, drop_height_m: t.drop_height_m ?? undefined }).then((c) => alive && setCmp(c));
      })
      .catch((e) => alive && setError(e instanceof ApiError ? e.message : "Could not load the result"));
    return () => {
      alive = false;
    };
  }, [testId, dataVersion]);

  const peak = test?.measured_peak_g ?? null;
  const shown = useCountUp(peak);

  if (!testId) {
    return (
      <div className="flex h-full items-center justify-center">
        <Button onClick={() => go("test")}>Go to the test stand</Button>
      </div>
    );
  }
  if (error) return <div className="p-10 text-center text-red-300">{error}</div>;
  if (!test || !series) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-12 w-12 animate-spin rounded-full border-4 border-telemetry/30 border-t-telemetry" />
      </div>
    );
  }

  const a = test.analysis;
  const det = a.detection;
  const phys = a.physics;
  const samp = a.sampling;
  const outcome = OUTCOME[test.outcome];
  const verdict = predictionVerdict(
    test.prediction_kind
      ? { kind: test.prediction_kind as "number" | "range" | "category", label: test.prediction_label, value_g: test.predicted_peak_g, low_g: test.predicted_low_g, high_g: test.predicted_high_g }
      : null,
    peak,
    gradeBand,
  );
  const errors = test.quality_flags.filter((f) => f.severity === "error");
  const warnings = test.quality_flags.filter((f) => f.severity === "warning");
  const infos = test.quality_flags.filter((f) => f.severity === "info" && f.code !== "SIMULATED");
  const range = a.saturation?.range_g ?? 16;
  // Recording lost, live stream kept: a lower bound only, never ranked.
  const liveOnly = test.quality_flags.some((f) => f.code === "LIVE_STREAM_ONLY") && test.observed_max_g != null;
  const young = gradeBand === "k4";
  const showAdvanced = gradeBand !== "k4";

  const cmpData = (cmp?.groups ?? [])
    .filter((g) => g.mean_peak_g !== null)
    .map((g) => ({ code: `${g.configuration_code} ${g.configuration_name ?? ""}`.trim(), mean: Number(g.mean_peak_g!.toFixed(2)), color: g.color === "#f8fafc" ? "#e2e8f0" : g.color, n: g.valid, isThis: g.configuration_code === test.configuration_code }));

  return (
    <div className="grid min-h-full grid-cols-1 gap-5 p-5 2xl:h-full 2xl:grid-cols-[440px_1fr]">
      <div className="flex flex-col gap-4 [&>*]:shrink-0 2xl:min-h-0 2xl:overflow-auto">
        <div className={`panel relative overflow-hidden p-5 text-center ${test.saturated && peak === null ? "border-alert/60" : ""}`}>
          {test.data_origin !== "physical" && (
            <div className={`mb-3 rounded-lg px-2 py-1 font-display text-[11px] font-bold tracking-[0.2em] ${test.data_origin === "simulated" ? "sim-stripes text-purple-100" : "bg-caution/20 text-amber-200"}`}>
              {ORIGIN_LABEL[test.data_origin]}
            </div>
          )}
          <div className="font-display text-sm tracking-[0.3em] text-telemetry">PEAK IMPACT ACCELERATION</div>
          {peak !== null ? (
            <div className="pop-in font-mono text-8xl font-black text-white glow-cyan">
              {shown.toFixed(1)}
              <span className="ml-2 text-5xl text-telemetry">g</span>
            </div>
          ) : null}
          {peak !== null && test.saturated && (
            <div className="mt-1 text-xs text-amber-200/90">An axis reached the sensor's ±{range} g limit, so the real peak may be a little higher.</div>
          )}
          {peak !== null ? null : liveOnly ? (
            <div className="pop-in py-2">
              <div className="font-mono text-7xl font-black text-amber-200">≥ {test.observed_max_g!.toFixed(1)} g</div>
              <div className="mt-1 font-display text-lg tracking-widest text-amber-200">APPROXIMATE · LIVE STREAM</div>
              <div className="mt-1 text-xs text-amber-100/80">The recording could not be downloaded. The real peak was at least this high.</div>
            </div>
          ) : test.saturated ? (
            <div className="pop-in py-2">
              <div className="font-mono text-7xl font-black text-red-300">
                {test.observed_max_g != null ? <>≥ {test.observed_max_g.toFixed(1)}</> : <>&gt; {range}</>} g
              </div>
              <div className="mt-1 font-display text-lg tracking-widest text-red-300">OVER SENSOR RANGE</div>
              <div className="mt-1 text-xs text-red-200/80">The real peak was at least this high.</div>
            </div>
          ) : (
            <div className="pop-in py-4 font-display text-3xl font-black text-red-300">NO VALID IMPACT</div>
          )}
          <div className="mt-2 text-sm text-slate-400">
            {test.configuration_code && (
              <>
                Landing gear <b className="text-slate-200">{test.configuration_code} · {test.configuration_name}</b> ·{" "}
              </>
            )}
            {fmtHeight(test.drop_height_m)} drop · {SOURCE_LABEL[test.source] ?? test.source}
          </div>
          {young && peak !== null && settingsCategory(peak) && (
            <div className="mt-3 text-2xl font-bold text-white">That was a <span className="text-mars">{settingsCategory(peak)}</span> landing!</div>
          )}
          <div className={`mt-4 rounded-2xl border-2 px-4 py-3 text-xl font-bold ${outcome.cls}`}>
            <span className="mr-2 text-3xl">{outcome.emoji}</span>
            {outcome.label}
          </div>
          {test.outcome !== "invalid" && <div className="mt-1 text-[11px] text-slate-500">Classroom challenge criteria — not certified engineering safety limits.</div>}
        </div>

        <Panel title="Prediction vs measured">
          <div className="grid grid-cols-2 gap-2">
            <Stat label="You predicted" value={describePrediction(test.prediction_kind ? { kind: test.prediction_kind as "number", label: test.prediction_label, value_g: test.predicted_peak_g } : null)} />
            <Stat
              label="Measured"
              value={
                peak !== null
                  ? fmtG(peak)
                  : liveOnly
                    ? `≥ ${test.observed_max_g!.toFixed(1)} g (approx.)`
                    : test.saturated
                      ? test.observed_max_g != null
                        ? `≥ ${test.observed_max_g.toFixed(1)} g`
                        : `> ${range} g`
                      : "—"
              }
              tone={peak !== null ? "default" : "alert"}
            />
          </div>
          {verdict && <div className={`mt-3 rounded-xl px-3 py-2 text-lg font-semibold ${verdict.good ? "bg-go/10 text-green-200" : "bg-space-850 text-slate-200"}`}>{verdict.text}</div>}
        </Panel>

        {test.saturated && peak !== null && (
          <div className="rounded-2xl border border-caution/40 bg-caution/10 p-4 text-amber-100">
            <div className="font-display text-sm tracking-widest">SENSOR LIMIT REACHED ON AN AXIS</div>
            <p className="mt-1 text-sm">
              The sensor measures each axis (X, Y, Z) up to ±{range} g, and {clippedAxes(a.saturation?.per_axis_counts)} reached that limit. The peak shown combines all
              three axes, so it can be above {range} g. Because that axis was cut off at its limit, the real peak may be a little higher. Use{" "}
              <i>X / Y / Z axes</i> on the graph to see it.
            </p>
          </div>
        )}
        {test.saturated && peak === null && (
          <div className="rounded-2xl border-2 border-alert/60 bg-red-950/40 p-4 text-red-100">
            <div className="font-display text-sm tracking-widest">⚠ SENSOR SATURATED</div>
            <p className="mt-1 text-sm">
              The sensor measures each axis (X, Y, Z) up to ±{range} g, and {clippedAxes(a.saturation?.per_axis_counts)} reached that limit. The graph shows |a|, which combines
              all three axes, so it can read above {range} g ({fmtG(test.observed_max_g)} here). Because an axis was cut off at its limit, the real peak was higher
              still, so this test is not used in rankings. Try a lower drop height or more cushioning.
            </p>
          </div>
        )}

        <Panel title="What does it mean?">
          <p className={young ? "text-lg text-slate-200" : "text-slate-300"}>
            {young
              ? "A smaller number means a gentler landing for the science sensor inside."
              : "Lower peak acceleration generally means less shock to the payload, assuming the measurements are valid and comparable (same drop height and landing surface)."}
          </p>
          {!young && <p className="mt-2 text-sm text-slate-400">Peak acceleration alone does not prove a lander is structurally safe — engineers also look at how long the shock lasts, rebounds, stability and the strength of every part.</p>}
          {a.outcome_reasons && test.outcome !== "invalid" && (
            <ul className="mt-2 list-inside list-disc text-sm text-slate-400">
              {a.outcome_reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
        </Panel>

        <div className="flex flex-wrap gap-3">
          <Button variant="mars" size="lg" onClick={() => go("design")} className="flex-1">
            Improve design ▶
          </Button>
          <Button variant="primary" size="lg" onClick={() => go("compare")} className="flex-1">
            Compare landings
          </Button>
          <Button variant="ghost" size="lg" onClick={newMission}>
            New mission
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-4 [&>*]:shrink-0 2xl:min-h-0 2xl:overflow-auto">
        {operatorUnlocked && <OperatorStrip test={test} onChange={setTest} />}
        <Panel title="Acceleration vs time" className="flex min-h-[380px] flex-col">
          <div className="min-h-[320px] flex-1">
            <ResultsChart series={series} peak={peak} saturated={test.saturated} rangeG={range} />
          </div>
        </Panel>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Panel title="Measurement quality" right={test.valid ? <Badge tone="go">valid</Badge> : <Badge tone="alert">invalid</Badge>}>
            <div className="grid grid-cols-3 gap-2">
              <Stat label="Sample rate" value={fmtNum(samp?.observed_rate_hz, 0, "Hz")} />
              <Stat label="Samples" value={samp?.sample_count ?? "—"} />
              <Stat label="Complete" value={samp?.completeness != null ? `${Math.round(samp.completeness * 100)}%` : "—"} />
            </div>
            <div className="mt-3 flex flex-col gap-1.5 text-sm">
              {errors.map((f) => (
                <div key={f.code + f.message} className="rounded-lg bg-alert/10 px-3 py-1.5 text-red-200">✖ {f.message}</div>
              ))}
              {warnings.map((f) => (
                <div key={f.code + f.message} className="rounded-lg bg-caution/10 px-3 py-1.5 text-amber-200">▲ {f.message}</div>
              ))}
              {infos.map((f) => (
                <div key={f.code + f.message} className="rounded-lg bg-space-850 px-3 py-1.5 text-slate-300">ℹ {f.message}</div>
              ))}
              {!errors.length && !warnings.length && <div className="rounded-lg bg-go/10 px-3 py-1.5 text-green-200">✔ No data-quality problems detected.</div>}
            </div>
          </Panel>

          <Panel title="Compare with other designs">
            {cmpData.length ? (
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={cmpData} layout="vertical" margin={{ left: 10, right: 40 }}>
                    <XAxis type="number" tick={{ fill: "#94a3b8", fontSize: 12 }} tickFormatter={(v: number) => `${v} g`} />
                    <YAxis type="category" dataKey="code" width={90} tick={{ fill: "#e2e8f0", fontSize: 13 }} />
                    <Bar dataKey="mean" radius={[0, 6, 6, 0]} maxBarSize={34} isAnimationActive={false}>
                      {cmpData.map((d) => (
                        <Cell key={d.code} fill={d.color} stroke={d.isThis ? "#fff" : "none"} strokeWidth={2} />
                      ))}
                      <LabelList dataKey="mean" position="right" fill="#e2e8f0" fontSize={12} formatter={(v) => `${v} g`} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="text-sm text-slate-400">No valid tests to compare yet at this drop height.</div>
            )}
            <div className="mt-1 text-[11px] text-slate-500">
              Average of valid {test.data_origin} tests at {fmtHeight(test.drop_height_m)}. Lower is gentler.
            </div>
          </Panel>
        </div>

        {showAdvanced && phys && (
          <Panel title="Engineering analysis">
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              <Stat label="Ideal impact speed" value={fmtNum(phys.impact_speed_m_s, 2, "m/s")} sub="v = √(2gh)" />
              <Stat label="Potential energy" value={fmtNum(phys.potential_energy_j, 2, "J")} sub={`E = mgh · m = ${fmtMass(test.mass_kg)}`} />
              <Stat label="Free fall (measured)" value={det?.freefall ? fmtNum(det.freefall.duration_ms, 0, "ms") : "—"} sub={det?.freefall ? `≈ ${fmtHeight(det.freefall.estimated_drop_height_m)} drop (½gt²)` : "not detected"} />
              <Stat label="Impact pulse width" value={fmtNum(det?.pulse_width_ms, 1, "ms")} sub={det?.samples_in_pulse ? `${det.samples_in_pulse} samples above half peak` : undefined} />
              {gradeBand === "912" && (
                <>
                  <Stat label="Gravity-compensated peak" value={fmtG(test.gravity_comp_peak_g)} sub="estimate: |a − a_rest|" />
                  <Stat label="Δv during impact" value={fmtNum(phys.estimated_delta_v_m_s, 2, "m/s")} sub="∫ a dt (estimate)" />
                  <Stat label="Time to peak" value={fmtNum(det?.time_to_peak_ms, 1, "ms")} />
                  <Stat label="Rebounds" value={det?.secondary.filter((e) => e.kind === "rebound").length ?? 0} />
                </>
              )}
            </div>
            {gradeBand === "912" && (
              <div className="mt-3 overflow-hidden rounded-xl border border-space-600">
                <table className="w-full text-sm">
                  <tbody>
                    <tr className="border-b border-space-700">
                      <td className="px-3 py-1.5 text-slate-400">Accelerometer specific force (measured)</td>
                      <td className="px-3 py-1.5 text-right font-mono">{fmtG(peak)}</td>
                    </tr>
                    <tr className="border-b border-space-700">
                      <td className="px-3 py-1.5 text-slate-400">Estimated net force on lander (m × a, gravity-compensated)</td>
                      <td className="px-3 py-1.5 text-right font-mono">{fmtNum(phys.estimated_net_force_n, 1, "N")}</td>
                    </tr>
                    <tr className="border-b border-space-700">
                      <td className="px-3 py-1.5 text-slate-400">Estimated total support force (m × specific force, rigid body)</td>
                      <td className="px-3 py-1.5 text-right font-mono">{fmtNum(phys.estimated_support_force_n, 1, "N")}</td>
                    </tr>
                    <tr>
                      <td className="px-3 py-1.5 text-slate-400">Actual contact force at the landing feet</td>
                      <td className="px-3 py-1.5 text-right text-amber-300">not measured</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            )}
            <ul className="mt-2 list-inside list-disc text-[11px] text-slate-500">
              {phys.assumptions.map((x) => (
                <li key={x}>{x}</li>
              ))}
              {phys.gravity_label !== "Earth" && <li>Gravity used: {phys.gravity_label} ({phys.gravity_m_s2.toFixed(2)} m/s²).</li>}
            </ul>
          </Panel>
        )}
      </div>
    </div>
  );

  function settingsCategory(p: number) {
    const crit = a.criteria;
    return crit ? measuredCategory(p, crit) : null;
  }
}

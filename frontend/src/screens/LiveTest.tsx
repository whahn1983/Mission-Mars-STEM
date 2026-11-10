import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import { LiveChart, LiveMagnitude } from "../components/LiveChart";
import { SensorChip } from "../components/Shell";
import { Badge, Button, Panel } from "../components/ui";
import { fmtG, fmtHeight, fmtMass } from "../lib/format";
import { describePrediction } from "../lib/predict";
import { useStore } from "../state/store";

const STEPS = [
  { id: "idle", label: "Ready" },
  { id: "baseline", label: "Baseline" },
  { id: "armed", label: "Armed" },
  { id: "triggered", label: "Impact" },
  { id: "analyzing", label: "Analyzing" },
] as const;

export function LiveTest() {
  const sensor = useStore((s) => s.sensor);
  const capture = useStore((s) => s.capture);
  const configs = useStore((s) => s.configurations);
  const configurationId = useStore((s) => s.configurationId);
  const prediction = useStore((s) => s.prediction);
  const gradeBand = useStore((s) => s.gradeBand);
  const settings = useStore((s) => s.settings);
  const dropHeight = useStore((s) => s.dropHeight);
  const setPreview = useStore((s) => s.setPreview);
  const showResult = useStore((s) => s.showResult);
  const notify = useStore((s) => s.notify);
  const go = useStore((s) => s.go);
  const [busy, setBusy] = useState(false);
  const prevState = useRef(capture?.state);
  // True when this screen started (or, after a browser refresh, resumed) the
  // test in progress, so it should jump to the results when it completes.
  const armedHere = useRef(["baseline", "armed", "triggered", "analyzing"].includes(capture?.state ?? ""));

  const cfg = configs.find((c) => c.id === configurationId) ?? null;
  const sim = sensor?.mode === "simulation";
  const state = capture?.state ?? "idle";
  const active = ["baseline", "armed", "triggered", "analyzing"].includes(state);
  const canStudentHeight = sim && settings?.allow_student_height_change;
  const height = active && capture?.mission ? capture.mission.drop_height_m : (canStudentHeight && dropHeight) || settings?.drop_height_m || 0.2;
  const sensorReady = !!sensor?.connected && sensor.streaming_available !== false;

  useEffect(() => {
    setPreview(true);
    return () => setPreview(false);
  }, [setPreview]);

  useEffect(() => {
    if (prevState.current !== "complete" && state === "complete" && capture?.test_id && armedHere.current) {
      armedHere.current = false;
      const id = capture.test_id;
      window.setTimeout(() => showResult(id), 400);
    }
    if (state === "baseline" || state === "armed") armedHere.current = true;
    prevState.current = state;
  }, [state, capture?.test_id, showResult]);

  const call = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      notify("error", e instanceof ApiError ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  const arm = () =>
    cfg &&
    call(async () => {
      armedHere.current = true;
      await api.arm({
        configuration_id: cfg.id,
        grade_band: gradeBand,
        prediction,
        ...(canStudentHeight && dropHeight ? { drop_height_m: dropHeight } : {}),
      });
    });
  const release = () => call(() => api.simulateDrop());

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      if (e.code === "Space") {
        e.preventDefault();
        if (!active && sensorReady) arm();
        else if (state === "armed" && sim) release();
      }
      if (e.key === "Escape" && active && state !== "analyzing") call(() => api.cancel());
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const stepIdx = STEPS.findIndex((s) => s.id === state);
  const range = sensor?.accel_range_g ?? 16;

  return (
    <div className="grid min-h-full grid-cols-1 gap-5 p-5 xl:h-full xl:grid-cols-[1fr_380px]">
      <div className="flex min-h-0 flex-col gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="font-display text-sm tracking-[0.35em] text-mars">LIVE TEST · DROP STAND</div>
          <SensorChip />
          {sensor?.data_origin === "simulated" && <Badge tone="sim">Simulated data — not a physical measurement</Badge>}
          {sensor?.data_origin === "unverified" && <Badge tone="caution">Replay — provenance not verified</Badge>}
        </div>

        <ol className="grid grid-cols-5 gap-2">
          {STEPS.map((s, i) => (
            <li
              key={s.id}
              className={`rounded-xl border px-3 py-2 text-center text-xs font-bold uppercase tracking-widest ${
                i === stepIdx ? "border-telemetry bg-telemetry/20 text-white" : i < stepIdx ? "border-telemetry/30 bg-telemetry/5 text-telemetry" : "border-space-600 bg-space-800/60 text-slate-500"
              }`}
            >
              {s.label}
            </li>
          ))}
        </ol>

        <div className={`panel relative flex min-h-[300px] flex-1 flex-col p-4 ${state === "triggered" ? "shake" : ""}`}>
          <div className="mb-2 flex items-end justify-between">
            <div>
              <div className="panel-title">Live acceleration magnitude</div>
              <div className="font-mono text-6xl font-black text-telemetry glow-cyan">
                <LiveMagnitude /> <span className="text-3xl text-telemetry/70">g</span>
              </div>
            </div>
            {capture?.live_peak_g && (state === "triggered" || state === "analyzing") ? (
              <div className="text-right">
                <div className="panel-title text-mars">Impact detected</div>
                <div className="font-mono text-3xl font-bold text-mars">{fmtG(capture.live_peak_g)}</div>
              </div>
            ) : null}
          </div>
          <div className="min-h-[220px] flex-1">
            <LiveChart rangeG={range} simulated={sim} />
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-4 [&>*]:shrink-0 xl:min-h-0 xl:overflow-auto">
        <Panel title="Mission">
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div className="text-slate-400">Landing gear</div>
            <div className="text-right font-bold" style={{ color: cfg?.display_color }}>
              {cfg ? `${cfg.code} · ${cfg.name}` : "—"}
            </div>
            <div className="text-slate-400">Mass</div>
            <div className="text-right font-mono">{fmtMass(cfg?.mass_kg)}</div>
            <div className="text-slate-400">Drop height</div>
            <div className="text-right font-mono">{fmtHeight(height)}</div>
            <div className="text-slate-400">Prediction</div>
            <div className="text-right font-mono">{describePrediction(prediction)}</div>
          </div>
        </Panel>

        {!sensorReady && (
          <div className="rounded-2xl border-2 border-alert/60 bg-red-950/50 p-4 text-red-100">
            <div className="font-display text-sm tracking-widest">SENSOR UNAVAILABLE</div>
            <p className="mt-1 text-sm">
              {sensor?.stream_error || sensor?.last_error || "The accelerometer is not connected."}{" "}
              {sensor?.connected && sensor.streaming_available === false
                ? "Operator: the sensor answers, but its data link is not set up yet, so reconnecting will not help. Switch to simulation mode or import a CSV in the dashboard."
                : "Operator: reconnect the sensor or switch to simulation mode in the dashboard."}
            </p>
          </div>
        )}

        <Panel title="Test control">
          <div className={`mb-4 rounded-xl p-3 text-center text-lg font-semibold ${state === "error" ? "bg-red-950/60 text-red-200" : state === "armed" ? "bg-mars/15 text-orange-200" : "bg-space-850 text-slate-200"}`}>
            {capture?.message ?? "Ready"}
          </div>

          {!active && (
            <Button variant="mars" size="xl" className="w-full font-display tracking-[0.25em]" disabled={!cfg || !sensorReady || busy} onClick={arm}>
              ARM TEST
            </Button>
          )}

          {state === "baseline" && (
            <div className="flex flex-col items-center gap-2 py-4 text-center text-slate-300">
              <div className="h-10 w-10 animate-spin rounded-full border-4 border-telemetry/30 border-t-telemetry" />
              Measuring the resting baseline. Keep the lander still.
            </div>
          )}

          {state === "armed" && sim && (
            <Button variant="sim" size="xl" className="w-full font-display tracking-[0.2em]" disabled={busy} onClick={release}>
              RELEASE ▼ (SIMULATED DROP)
            </Button>
          )}
          {state === "armed" && !sim && (
            <div className="animate-pulse rounded-2xl border-2 border-mars bg-mars/15 p-5 text-center font-display text-2xl font-black tracking-widest text-mars">
              RELEASE THE LANDER!
            </div>
          )}
          {state === "triggered" && <div className="rounded-2xl bg-mars/20 p-5 text-center font-display text-3xl font-black text-mars">IMPACT!</div>}
          {state === "analyzing" && (
            <div className="flex flex-col items-center gap-2 py-4 text-slate-300">
              <div className="h-10 w-10 animate-spin rounded-full border-4 border-mars/30 border-t-mars" />
              Analyzing landing data…
            </div>
          )}

          <div className="mt-4 grid grid-cols-3 gap-2">
            <Button variant="ghost" size="md" disabled={!["baseline", "armed"].includes(state) || busy} onClick={() => call(() => api.trigger())} title="Record the next window manually">
              Capture
            </Button>
            <Button variant="ghost" size="md" disabled={!["baseline", "armed", "triggered"].includes(state) || busy} onClick={() => call(() => api.stop())} title="Stop and analyze what was recorded">
              Stop
            </Button>
            <Button variant="ghost" size="md" disabled={!active || state === "analyzing" || busy} onClick={() => call(() => api.cancel())}>
              Cancel
            </Button>
          </div>
          {state === "complete" && capture?.test_id && (
            <Button variant="primary" size="md" className="mt-3 w-full" onClick={() => showResult(capture.test_id!)}>
              View last result ▶
            </Button>
          )}
          <p className="mt-3 text-xs text-slate-500">
            {sim ? "Space = arm / release." : "Space = arm. The operator releases the lander; the impact is detected automatically."} Esc = cancel.
          </p>
        </Panel>

        <Button variant="ghost" onClick={() => go("predict")} disabled={active}>
          ◀ Change prediction
        </Button>
      </div>
    </div>
  );
}

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, setOperatorPin } from "../api/client";
import type { Configuration, DiagnosticsReport, LogEntry, ProbeResult, SensorMode, SessionInfo, SystemSettings, SystemView, TestSummary } from "../api/types";
import { Badge, Button, Field, inputCls, Modal, Panel, Segmented, Stat, Toggle } from "../components/ui";
import { ago, fmtDateTime, fmtG, fmtHeight, fmtNum, SOURCE_LABEL } from "../lib/format";
import { useStore } from "../state/store";

type Tab = "station" | "system" | "sensor" | "gear" | "data" | "analysis" | "logs";

function useAction() {
  const notify = useStore((s) => s.notify);
  const [busy, setBusy] = useState(false);
  const run = useCallback(
    async <T,>(fn: () => Promise<T>, ok?: string): Promise<T | undefined> => {
      setBusy(true);
      try {
        const r = await fn();
        if (ok) notify("success", ok);
        return r;
      } catch (e) {
        notify("error", e instanceof ApiError ? e.message : String(e));
        return undefined;
      } finally {
        setBusy(false);
      }
    },
    [notify],
  );
  return { busy, run };
}

function PinGate() {
  const unlock = useStore((s) => s.unlockOperator);
  const [pin, setPin] = useState("");
  const [bad, setBad] = useState(false);
  const submit = async () => {
    const ok = await unlock(pin);
    setBad(!ok);
    if (!ok) setPin("");
  };
  return (
    <div className="flex flex-col items-center gap-4 py-6">
      <p className="text-slate-300">Enter the operator PIN to open the dashboard.</p>
      <input
        autoFocus
        type="password"
        inputMode="numeric"
        className={`${inputCls} w-48 text-center font-mono text-3xl tracking-[0.5em]`}
        value={pin}
        onChange={(e) => setPin(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
      />
      {bad && <div className="text-red-300">Incorrect PIN</div>}
      <Button onClick={submit}>Unlock</Button>
      <p className="text-xs text-slate-500">The PIN is set with OPERATOR_PIN in the .env file.</p>
    </div>
  );
}

// ---------------------------------------------------------------------------------- station
function StationTab({ settings, reload }: { settings: Record<string, unknown>; reload: () => void }) {
  const { busy, run } = useAction();
  const capture = useStore((s) => s.capture);
  const openOperator = useStore((s) => s.openOperator);
  const configurationId = useStore((s) => s.configurationId);
  const gradeBand = useStore((s) => s.gradeBand);
  const prediction = useStore((s) => s.prediction);
  const mission = { configurationId, gradeBand, prediction };
  const [heightCm, setHeightCm] = useState(String(Math.round(Number(settings.drop_height_m) * 100)));
  const [options, setOptions] = useState(((settings.drop_height_options_m as number[]) ?? []).map((h) => Math.round(h * 100)).join(", "));
  const save = (changes: Record<string, unknown>, msg = "Saved") => run(() => api.updateSettings(changes), msg).then(reload);

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Panel title="Station control">
        <div className="flex flex-col gap-3">
          <Button
            variant="mars"
            size="lg"
            disabled={busy}
            onClick={() =>
              run(() => api.operatorReset(), "Station reset — all screens back to the Mission Briefing").then(() => openOperator(false))
            }
          >
            ⟲ Reset student mission (all screens)
          </Button>
          <div className="text-sm text-slate-400">
            Capture state: <b className="text-slate-200">{capture?.state}</b> — {capture?.message}
          </div>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <Button
              variant="ghost"
              disabled={busy || !mission.configurationId}
              title="Arm using the landing gear and prediction currently chosen on the student screen"
              onClick={() =>
                run(
                  () => api.arm({ configuration_id: mission.configurationId!, grade_band: mission.gradeBand, prediction: mission.prediction }),
                  "Armed",
                )
              }
            >
              Arm test
            </Button>
            <Button variant="ghost" disabled={busy} title="Start the post-trigger recording window now" onClick={() => run(() => api.trigger(), "Manual capture started")}>
              Capture now
            </Button>
            <Button variant="ghost" disabled={busy} onClick={() => run(() => api.stop(), "Capture stopped")}>
              Stop &amp; analyze
            </Button>
            <Button variant="danger" disabled={busy} onClick={() => run(() => api.cancel(), "Current test cleared")}>
              Clear current test
            </Button>
          </div>
        </div>
      </Panel>

      <Panel title="Drop height">
        <div className="flex flex-col gap-3">
          <div className="flex items-end gap-2">
            <Field label="Current drop height (cm)">
              <input className={inputCls} value={heightCm} onChange={(e) => setHeightCm(e.target.value)} inputMode="decimal" />
            </Field>
            <Button disabled={busy} onClick={() => save({ drop_height_m: Number(heightCm) / 100 }, "Drop height saved")}>
              Set
            </Button>
          </div>
          <div className="flex items-end gap-2">
            <Field label="Height options shown to students in simulation (cm)" hint="Comma-separated, e.g. 10, 20, 30">
              <input className={inputCls} value={options} onChange={(e) => setOptions(e.target.value)} />
            </Field>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() =>
                save({
                  drop_height_options_m: options
                    .split(",")
                    .map((x) => Number(x.trim()) / 100)
                    .filter((x) => x > 0 && x <= 3),
                })
              }
            >
              Save
            </Button>
          </div>
          <Toggle
            checked={!!settings.allow_student_height_change}
            onChange={(v) => save({ allow_student_height_change: v })}
            label="Students may change the drop height (simulation only)"
          />
          <p className="text-xs text-slate-500">
            Physical tests always use the height set here. Keep drops low enough that the ±16 g sensor does not saturate (see docs: drop-height planning).
          </p>
        </div>
      </Panel>

      <Panel title="Simulation">
        <div className="flex flex-col gap-3">
          <Field label="Simulated gravity">
            <Segmented
              value={(settings.sim_gravity as string) === "mars" ? "mars" : "earth"}
              onChange={(v) => save({ sim_gravity: v })}
              options={[
                { value: "earth", label: "Earth 9.81 m/s²" },
                { value: "mars", label: "Mars 3.72 m/s² (simulation only)" },
              ]}
            />
          </Field>
          <Toggle checked={!!settings.sim_use_fixed_seed} onChange={(v) => save({ sim_use_fixed_seed: v })} label="Reproducible simulation (fixed random seed)" />
          <Field label="Seed">
            <input className={inputCls} defaultValue={String(settings.sim_seed ?? 2026)} onBlur={(e) => save({ sim_seed: Number(e.target.value) || 0 })} />
          </Field>
        </div>
      </Panel>

      <Panel title="Kiosk">
        <div className="flex flex-col gap-3">
          <Field label="Return to briefing after idle (seconds, 0 = never)">
            <input
              className={inputCls}
              defaultValue={String(settings.idle_reset_seconds ?? 120)}
              onBlur={(e) => save({ idle_reset_seconds: Math.max(0, Number(e.target.value) || 0) })}
            />
          </Field>
          <Button variant="ghost" onClick={() => document.documentElement.requestFullscreen().catch(() => undefined)}>
            Enter full screen
          </Button>
          <p className="text-xs text-slate-500">Shortcuts: Ctrl+Shift+O operator · Ctrl+Shift+H home · Enter next · 1–4 choose · Space arm/release · Esc cancel.</p>
        </div>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------------------- sensor
function SensorTab() {
  const sensor = useStore((s) => s.sensor);
  const { busy, run } = useAction();
  const [host, setHost] = useState(sensor?.host ?? "");
  const [port, setPort] = useState(String(sensor?.port ?? 80));
  const [diag, setDiag] = useState<DiagnosticsReport | null>(null);
  const [probePath, setProbePath] = useState("/");
  const [probe, setProbe] = useState<ProbeResult | null>(null);
  const [replayOrigin, setReplayOrigin] = useState("unverified");
  const [replayLoop, setReplayLoop] = useState(false);

  useEffect(() => {
    if (sensor?.host !== undefined) setHost((h) => h || sensor.host || "");
  }, [sensor?.host]);

  if (!sensor) return null;
  const modes: { value: SensorMode; label: string }[] = [
    { value: "simulation", label: "Simulation" },
    { value: "evb_lite", label: "EVB Lite (real sensor)" },
    { value: "csv_replay", label: "CSV replay" },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Panel title="Sensor mode">
        <Segmented value={sensor.mode} onChange={(m) => run(() => api.setMode(m), `Switched to ${m}`)} options={modes} />
        {sensor.mode !== "simulation" && (
          <Button className="mt-3" variant="sim" disabled={busy} onClick={() => run(() => api.setMode("simulation"), "Switched to simulation")}>
            Switch to simulation now
          </Button>
        )}
        <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-3">
          <Stat label="State" value={sensor.state} tone={sensor.connected ? "go" : "alert"} />
          <Stat label="Observed rate" value={fmtNum(sensor.observed_rate_hz, 0, "Hz")} sub={sensor.nominal_rate_hz ? `nominal ${Math.round(sensor.nominal_rate_hz)} Hz` : undefined} />
          <Stat label="Last contact" value={ago(sensor.seconds_since_success)} />
          <Stat label="Model" value={<span className="text-sm">{sensor.model ?? "—"}</span>} />
          <Stat label="Firmware" value={<span className="text-sm">{sensor.firmware_version ?? "—"}</span>} />
          <Stat label="Battery" value={sensor.battery_percent != null ? `${sensor.battery_percent}%` : "n/a"} sub={sensor.battery_percent == null ? "not reported" : undefined} />
          <Stat label="Range" value={`±${sensor.accel_range_g} g`} />
          <Stat label="Samples" value={sensor.samples_received} />
          <Stat label="Failures" value={sensor.consecutive_failures} sub={sensor.next_retry_in_s != null ? `retry in ${sensor.next_retry_in_s}s` : undefined} />
        </div>
        {sensor.capture_mode === "record" && sensor.sensor_settings && Object.keys(sensor.sensor_settings).length > 0 && (
          <div className="mt-3 rounded-xl border border-space-600 p-3 text-sm">
            <div className="mb-1 font-semibold">Sensor's own settings (read from the sensor)</div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-slate-300">
              {sensor.sensor_settings.duration_s != null && <span>Recording time {sensor.sensor_settings.duration_s} s</span>}
              {sensor.sensor_settings.accel_range_g != null && (
                <span className={sensor.sensor_settings.accel_range_g < 16 ? "text-amber-200" : undefined}>Range ±{sensor.sensor_settings.accel_range_g} g</span>
              )}
              {sensor.sensor_settings.sample_rate_hz != null && <span>Rate {sensor.sensor_settings.sample_rate_hz} Hz</span>}
              {sensor.sensor_settings.gravity_comp != null && (
                <span className={sensor.sensor_settings.gravity_comp ? "font-semibold text-red-300" : undefined}>
                  Gravity compensation {sensor.sensor_settings.gravity_comp ? "ON: turn it off in the sensor portal" : "off"}
                </span>
              )}
            </div>
            {sensor.live_view && (
              <div className="mt-1 text-slate-300">
                Live view:{" "}
                {sensor.live_view.running
                  ? `running${sensor.live_view.rate_hz ? `, ~${Math.round(sensor.live_view.rate_hz)} Hz` : ""}${sensor.live_view.unit ? `, ${sensor.live_view.unit}` : ""} (display only)`
                  : sensor.live_view.error
                    ? <span className="text-amber-200">unavailable: {sensor.live_view.error}</span>
                    : "off (starts on the Live Test screen)"}
              </div>
            )}
            <div className="mt-1 text-xs text-slate-500">ARM TEST sets the sensor's recording time to the app's "EVB Lite: test length" (Analysis tab).</div>
          </div>
        )}
        {sensor.last_error && <div className="mt-3 rounded-lg bg-alert/10 px-3 py-2 text-sm text-red-200">Last error: {sensor.last_error}</div>}
        {sensor.stream_error && <div className="mt-2 rounded-lg bg-caution/10 px-3 py-2 text-sm text-amber-200">{sensor.stream_error}</div>}
        <div className="mt-3 flex gap-2">
          <Button variant="ghost" disabled={busy} onClick={() => run(() => api.connect(), "Reconnecting")}>
            Connect / retry now
          </Button>
          <Button variant="ghost" disabled={busy} onClick={() => run(() => api.disconnect(), "Disconnected")}>
            Disconnect
          </Button>
        </div>
      </Panel>

      <Panel title="EVB Lite network address">
        <div className="grid grid-cols-[1fr_100px] gap-2">
          <Field label="Sensor IP address" hint="From the UniFi client list / DHCP leases. Prefer an IP over a .local name (mDNS rarely works inside Docker).">
            <input className={inputCls} value={host} placeholder="192.168.1.50" onChange={(e) => setHost(e.target.value)} />
          </Field>
          <Field label="Port">
            <input className={inputCls} value={port} onChange={(e) => setPort(e.target.value)} />
          </Field>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button disabled={busy} onClick={() => run(() => api.configureEvb({ host, port: Number(port) || 80 }), "Sensor address saved")}>
            Save address
          </Button>
          <Button variant="ghost" disabled={busy} onClick={() => run(() => api.diagnostics()).then((d) => d && setDiag(d))}>
            Run diagnostics
          </Button>
          <Button variant="ghost" disabled={busy} onClick={() => run(() => api.reloadProfile(), "Profile reloaded")}>
            Reload EVB profile
          </Button>
        </div>
        {sensor.profile && (
          <div className="mt-3 rounded-xl border border-space-600 p-3 text-sm">
            <div className="mb-1 flex items-center gap-2">
              Protocol profile {sensor.profile.verified ? <Badge tone="go">verified</Badge> : <Badge tone="caution">not verified</Badge>}
              {sensor.profile.streaming_ready ? (
                <Badge tone="go">{sensor.profile.capture_mode === "record" ? "record mode ready" : "live capture ready"}</Badge>
              ) : (
                <Badge tone="muted">reachability only</Badge>
              )}
            </div>
            <div className="text-slate-400">
              {sensor.profile.verified
                ? `Verified by ${sensor.profile.verified_by || "?"} on ${sensor.profile.verified_on || "?"} — ${sensor.profile.source_of_truth}`
                : "EVB Lite data endpoints have not been verified on the real device. Live capture stays disabled; use simulation or CSV import. See docs/evb-lite-integration.md."}
            </div>
            {sensor.profile.problems.map((p) => (
              <div key={p} className="mt-1 text-red-300">• {p}</div>
            ))}
          </div>
        )}
        {diag && (
          <div className="mt-3 rounded-xl border border-space-600 p-3 text-sm">
            <div className="mb-2 font-semibold">Diagnostics for {diag.host}:{diag.port} {diag.ok ? <Badge tone="go">OK</Badge> : <Badge tone="alert">problem</Badge>}</div>
            {diag.steps.map((s) => (
              <div key={s.name} className={s.ok ? "text-green-300" : "text-red-300"}>
                {s.ok ? "✔" : "✖"} {s.name}: {s.detail} {s.ms ? <span className="text-slate-500">({s.ms} ms)</span> : null}
              </div>
            ))}
            {diag.hints.map((h) => (
              <div key={h} className="mt-1 text-amber-200">→ {h}</div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Discovery probe (read-only HTTP GET)" className="lg:col-span-2">
        <p className="mb-2 text-sm text-slate-400">
          Fetch a page from the sensor's local web interface to document its behavior. Only GET requests are sent; responses are saved under /data/discovery. Use paths you found in the manufacturer documentation or the device portal — do not guess.
        </p>
        <div className="flex gap-2">
          <input className={`${inputCls} font-mono`} value={probePath} onChange={(e) => setProbePath(e.target.value)} />
          <Button variant="ghost" disabled={busy} onClick={() => run(() => api.probe(probePath)).then((p) => p && setProbe(p))}>
            GET
          </Button>
        </div>
        {probe && (
          <div className="mt-3 text-sm">
            <div className={probe.error ? "text-red-300" : "text-green-300"}>{probe.summary}</div>
            {probe.saved_to && <div className="text-xs text-slate-500">Saved to {probe.saved_to}</div>}
            {probe.headers && (
              <pre className="mt-2 max-h-32 overflow-auto rounded-lg bg-space-950 p-2 text-xs text-slate-400">
                {Object.entries(probe.headers)
                  .map(([k, v]) => `${k}: ${v}`)
                  .join("\n")}
              </pre>
            )}
            {(probe.body_text || probe.body_base64) && (
              <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-space-950 p-2 font-mono text-xs text-slate-300">
                {(probe.body_text ?? `[binary, base64]\n${probe.body_base64}`).slice(0, 20000)}
              </pre>
            )}
          </div>
        )}
      </Panel>

      <Panel title="CSV replay" className="lg:col-span-2">
        <p className="mb-2 text-sm text-slate-400">Replay a recorded CSV (e.g. exported from the manufacturer's Device Hub) as if it were live. Columns: a timestamp column and three acceleration columns.</p>
        <div className="flex flex-wrap items-center gap-3">
          <Segmented
            value={replayOrigin}
            onChange={setReplayOrigin}
            size="sm"
            options={[
              { value: "unverified", label: "Provenance unknown" },
              { value: "physical", label: "Recorded by the EVB Lite" },
              { value: "simulated", label: "Synthetic" },
            ]}
          />
          <Toggle checked={replayLoop} onChange={setReplayLoop} label="Loop" />
          <input
            type="file"
            accept=".csv,text/csv"
            className="text-sm"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) run(() => api.uploadReplay(f, { data_origin: replayOrigin, loop: replayLoop }), "Replay file loaded");
              e.target.value = "";
            }}
          />
        </div>
        {sensor.replay?.file && (
          <div className="mt-2 text-sm text-slate-300">
            Loaded: {sensor.replay.file} ({sensor.replay.rows} rows, {sensor.replay.data_origin})
          </div>
        )}
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------------------- gear
function GearRow({ c, onSaved }: { c: Configuration; onSaved: () => void }) {
  const { busy, run } = useAction();
  const [name, setName] = useState(c.name);
  const [material, setMaterial] = useState(c.material);
  const [massG, setMassG] = useState(String(Math.round(c.mass_kg * 1000)));
  const [color, setColor] = useState(c.display_color);
  const [desc, setDesc] = useState(c.description);
  const [paramsText, setParamsText] = useState(JSON.stringify(c.parameters_json, null, 2));
  const [showParams, setShowParams] = useState(false);
  const notify = useStore((s) => s.notify);
  const save = (changes: Partial<Configuration>, msg = "Saved") => run(() => api.updateConfiguration(c.id, changes), msg).then(onSaved);
  const saveParams = () => {
    try {
      const parsed = JSON.parse(paramsText);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw new Error("must be an object");
      save({ parameters_json: parsed }, "Parameters saved");
    } catch (e) {
      notify("error", `Invalid JSON: ${(e as Error).message}`);
    }
  };
  return (
    <div className={`rounded-2xl border p-4 ${c.enabled ? "border-telemetry/30" : "border-space-600 opacity-70"}`}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg font-display text-xl font-black text-space-950" style={{ background: color }}>
            {c.code}
          </div>
          <Toggle checked={c.enabled} onChange={(v) => save({ enabled: v }, v ? "Enabled" : "Disabled")} label={c.enabled ? "Built & available" : "Not available"} />
        </div>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => run(() => api.restoreConfiguration(c.id), "Defaults restored").then(onSaved)}>
          Restore defaults
        </Button>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Field label="Name">
          <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Material">
          <input className={inputCls} value={material} onChange={(e) => setMaterial(e.target.value)} />
        </Field>
        <Field label="Measured mass (g)" hint="Weigh the complete lander">
          <input className={inputCls} value={massG} onChange={(e) => setMassG(e.target.value)} inputMode="decimal" />
        </Field>
        <Field label="Color">
          <input type="color" className="h-10 w-full rounded-lg bg-transparent" value={color} onChange={(e) => setColor(e.target.value)} />
        </Field>
      </div>
      <Field label="Description">
        <textarea className={`${inputCls} mt-1`} rows={2} value={desc} onChange={(e) => setDesc(e.target.value)} />
      </Field>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button
          size="sm"
          disabled={busy}
          onClick={() => save({ name, material, description: desc, display_color: color, mass_kg: Math.max(1, Number(massG) || 1) / 1000 })}
        >
          Save
        </Button>
        <label className="text-sm text-slate-400">
          Photo:{" "}
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="text-sm"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) run(() => api.uploadPhoto(c.id, f), "Photo uploaded").then(onSaved);
            }}
          />
        </label>
        {c.photo_url && (
          <>
            <img src={c.photo_url} className="h-12 w-12 rounded object-cover" alt="" />
            <Button size="sm" variant="ghost" onClick={() => run(() => api.deletePhoto(c.id), "Photo removed").then(onSaved)}>
              Remove photo
            </Button>
          </>
        )}
        <Button size="sm" variant="ghost" onClick={() => setShowParams((v) => !v)}>
          {showParams ? "Hide" : "Advanced:"} 3D &amp; simulation parameters
        </Button>
      </div>
      {showParams && (
        <div className="mt-3">
          <p className="mb-1 text-xs text-slate-500">
            <code>geometry</code> controls the 3D drawing, <code>sim</code> the simulator (see docs/simulation-model.md), <code>traits</code> the 1–5 ratings.
          </p>
          <textarea className={`${inputCls} font-mono text-xs`} rows={14} value={paramsText} onChange={(e) => setParamsText(e.target.value)} spellCheck={false} />
          <Button size="sm" className="mt-2" disabled={busy} onClick={saveParams}>
            Save parameters
          </Button>
        </div>
      )}
    </div>
  );
}

function GearTab() {
  const configs = useStore((s) => s.configurations);
  const refresh = useStore((s) => s.refreshConfigurations);
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-slate-400">Enable only the landing-gear versions that have physically been built. Enter the measured mass of each complete lander.</p>
      {configs.map((c) => (
        <GearRow key={`${c.id}-${c.updated_at}`} c={c} onSaved={refresh} />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------------- data
function DataTab() {
  const { busy, run } = useAction();
  const showResult = useStore((s) => s.showResult);
  const openOperator = useStore((s) => s.openOperator);
  const configs = useStore((s) => s.configurations);
  const dataVersion = useStore((s) => s.dataVersion);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [tests, setTests] = useState<TestSummary[]>([]);
  const [sessionName, setSessionName] = useState("");
  const [filter, setFilter] = useState<number | "">("");
  const [imp, setImp] = useState({ configuration_id: "", drop_height_cm: "20", data_origin: "unverified", time_unit: "", accel_unit: "" });

  const load = useCallback(() => {
    api.sessions().then(setSessions).catch(() => undefined);
    api.tests({ session_id: filter === "" ? null : filter, limit: 300 }).then(setTests).catch(() => undefined);
  }, [filter]);
  useEffect(load, [load, dataVersion]);

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[380px_1fr]">
      <div className="flex flex-col gap-4">
        <Panel title="Sessions">
          <div className="flex gap-2">
            <input className={inputCls} placeholder="STEM Night 2026-11-13" value={sessionName} onChange={(e) => setSessionName(e.target.value)} />
            <Button disabled={busy} onClick={() => run(() => api.createSession(sessionName), "New session started").then(load)}>
              New
            </Button>
          </div>
          <div className="mt-3 flex max-h-60 flex-col gap-1 overflow-auto text-sm">
            {sessions.map((s) => (
              <div key={s.id} className="flex items-center justify-between rounded-lg bg-space-850 px-2 py-1.5">
                <span>
                  {s.active && <Badge tone="go">active</Badge>} {s.name} <span className="text-slate-500">({s.test_count})</span>
                </span>
                {!s.ended_at && (
                  <Button size="sm" variant="ghost" onClick={() => run(() => api.endSession(s.id), "Session ended").then(load)}>
                    End
                  </Button>
                )}
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Export">
          <div className="flex flex-col gap-2">
            <a className="rounded-xl bg-telemetry px-4 py-2 text-center font-semibold text-space-950" href={api.exportUrl("/api/export/tests.csv", { session_id: filter === "" ? null : filter })}>
              ⬇ Test results (CSV)
            </a>
            <a className="rounded-xl bg-space-700 px-4 py-2 text-center font-semibold" href={api.exportUrl("/api/export/session.zip", { session_id: filter === "" ? null : filter })}>
              ⬇ Full bundle: results + raw samples + analysis (ZIP)
            </a>
            <p className="text-xs text-slate-500">Exports follow the session filter on the right. No personal information is stored.</p>
          </div>
        </Panel>
        <Panel title="Import CSV as a test">
          <div className="grid grid-cols-2 gap-2">
            <Field label="Gear">
              <select className={inputCls} value={imp.configuration_id} onChange={(e) => setImp({ ...imp, configuration_id: e.target.value })}>
                <option value="">—</option>
                {configs.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.code} {c.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Drop height (cm)">
              <input className={inputCls} value={imp.drop_height_cm} onChange={(e) => setImp({ ...imp, drop_height_cm: e.target.value })} />
            </Field>
            <Field label="Data origin">
              <select className={inputCls} value={imp.data_origin} onChange={(e) => setImp({ ...imp, data_origin: e.target.value })}>
                <option value="unverified">Unverified</option>
                <option value="physical">Physical (EVB Lite)</option>
                <option value="simulated">Simulated</option>
              </select>
            </Field>
            <Field label="Time unit (if column is 'time')">
              <select className={inputCls} value={imp.time_unit} onChange={(e) => setImp({ ...imp, time_unit: e.target.value })}>
                <option value="">auto (EVB Lite file: µs, otherwise s)</option>
                <option value="s">s</option>
                <option value="ms">ms</option>
                <option value="us">µs</option>
                <option value="ns">ns</option>
              </select>
            </Field>
            <Field label="Acceleration unit">
              <select className={inputCls} value={imp.accel_unit} onChange={(e) => setImp({ ...imp, accel_unit: e.target.value })}>
                <option value="">auto (EVB Lite file: m/s², otherwise g)</option>
                <option value="g">g</option>
                <option value="mg">mg</option>
                <option value="m/s2">m/s²</option>
              </select>
            </Field>
          </div>
          <input
            type="file"
            accept=".csv,text/csv"
            className="mt-3 text-sm"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (!f) return;
              run(
                () =>
                  api.importCsv(f, {
                    configuration_id: imp.configuration_id ? Number(imp.configuration_id) : undefined,
                    drop_height_m: imp.drop_height_cm ? Number(imp.drop_height_cm) / 100 : undefined,
                    data_origin: imp.data_origin,
                    time_unit: imp.time_unit || undefined,
                    accel_unit: imp.accel_unit || undefined,
                  }),
                "CSV imported",
              ).then(load);
            }}
          />
        </Panel>
      </div>

      <Panel
        title="Test history"
        right={
          <select className="rounded-lg border border-telemetry/20 bg-space-850 px-2 py-1 text-sm" value={filter} onChange={(e) => setFilter(e.target.value ? Number(e.target.value) : "")}>
            <option value="">All sessions</option>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        }
      >
        <div className="max-h-[65vh] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-space-800 text-left text-xs uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-2 py-1">#</th>
                <th>Time</th>
                <th>Origin</th>
                <th>Gear</th>
                <th>Height</th>
                <th className="pr-3 text-right">Peak</th>
                <th className="pl-1">Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {tests.map((t) => (
                <tr key={t.id} className={`border-t border-space-700 ${t.excluded ? "opacity-50" : ""}`}>
                  <td className="px-2 py-1 font-mono text-slate-500">{t.id}</td>
                  <td>{fmtDateTime(t.timestamp)}</td>
                  <td>
                    <Badge tone={t.data_origin === "physical" ? "go" : t.data_origin === "simulated" ? "sim" : "caution"}>{t.data_origin}</Badge>
                    <div className="text-[10px] text-slate-500">{SOURCE_LABEL[t.source] ?? t.source}</div>
                  </td>
                  <td>
                    {t.configuration_code} {t.configuration_name}
                  </td>
                  <td>{fmtHeight(t.drop_height_m)}</td>
                  <td className="pr-3 text-right font-mono">{t.measured_peak_g != null ? fmtG(t.measured_peak_g, 2) : t.saturated ? `>${fmtG(t.observed_max_g, 1)}` : "—"}</td>
                  <td className="pl-1">
                    {t.saturated ? <Badge tone="alert">over range</Badge> : t.valid ? <Badge tone="go">valid</Badge> : <Badge tone="muted">invalid</Badge>}
                    {t.excluded && <Badge tone="caution">excluded</Badge>}
                  </td>
                  <td className="whitespace-nowrap text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        showResult(t.id);
                        openOperator(false);
                      }}
                    >
                      View
                    </Button>{" "}
                    <Button size="sm" variant="ghost" onClick={() => run(() => api.updateTest(t.id, { excluded: !t.excluded, exclude_reason: t.excluded ? null : "excluded by operator" })).then(load)}>
                      {t.excluded ? "Include" : "Exclude"}
                    </Button>{" "}
                    <a className="text-xs text-telemetry underline" href={`/api/tests/${t.id}/samples.csv`}>
                      CSV
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!tests.length && <div className="p-6 text-center text-slate-500">No tests recorded yet.</div>}
        </div>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------------------- analysis
function NumberField({ label, value, onSave, hint }: { label: string; value: unknown; onSave: (v: number) => void; hint?: ReactNode }) {
  return (
    <Field label={label} hint={hint}>
      <input
        className={inputCls}
        defaultValue={value === undefined || value === null ? "" : String(value)}
        inputMode="decimal"
        onBlur={(e) => {
          const v = Number(e.target.value);
          if (e.target.value !== "" && Number.isFinite(v)) onSave(v);
        }}
      />
    </Field>
  );
}

function AnalysisTab({ settings, reload }: { settings: Record<string, unknown>; reload: () => void }) {
  const { run } = useAction();
  const criteria = (settings.criteria ?? {}) as Record<string, number | boolean>;
  const detector = (settings.detector ?? {}) as Record<string, number>;
  const save = (changes: Record<string, unknown>) => run(() => api.updateSettings(changes), "Saved").then(reload);
  const saveCriteria = (k: string, v: unknown) => save({ criteria: { ...criteria, [k]: v } });
  const saveDetector = (k: string, v: unknown) => save({ detector: { ...detector, [k]: v } });

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Panel title="Classroom challenge criteria">
        <p className="mb-3 text-xs text-slate-500">These are classroom challenge thresholds, not certified engineering safety limits.</p>
        <div className="grid grid-cols-2 gap-3">
          <NumberField label="Success: peak at most (g)" value={criteria.success_max_peak_g} onSave={(v) => saveCriteria("success_max_peak_g", v)} />
          <NumberField label="Mass budget (g)" value={Math.round(Number(criteria.mass_budget_kg ?? 0.35) * 1000)} onSave={(v) => saveCriteria("mass_budget_kg", v / 1000)} />
          <NumberField label="Grades 1–4: Gentle below (g)" value={criteria.gentle_max_g} onSave={(v) => saveCriteria("gentle_max_g", v)} />
          <NumberField label="Grades 1–4: Medium below (g)" value={criteria.medium_max_g} onSave={(v) => saveCriteria("medium_max_g", v)} />
        </div>
        <div className="mt-3 flex flex-col gap-2">
          <Toggle checked={!!criteria.require_payload_retained} onChange={(v) => saveCriteria("require_payload_retained", v)} label="Payload must stay in place" />
          <Toggle checked={!!criteria.require_stable_landing} onChange={(v) => saveCriteria("require_stable_landing", v)} label="Lander must land upright" />
        </div>
      </Panel>
      <Panel title="Capture & detection">
        <div className="grid grid-cols-2 gap-3">
          <NumberField label="Pre-trigger buffer (s)" value={settings.pre_trigger_s} onSave={(v) => save({ pre_trigger_s: v })} />
          <NumberField label="Post-trigger window (s)" value={settings.post_trigger_s} onSave={(v) => save({ post_trigger_s: v })} />
          <NumberField label="Baseline duration (s)" value={settings.baseline_s} onSave={(v) => save({ baseline_s: v })} />
          <NumberField label="Arm timeout (s)" value={settings.arm_timeout_s} onSave={(v) => save({ arm_timeout_s: v })} />
          <NumberField
            label="EVB Lite: test length (s)"
            value={settings.record_window_s}
            onSave={(v) => save({ record_window_s: v })}
            hint="Each EVB Lite test records this long (default 10 s); the lander is released during the countdown. 0 = keep the sensor's own time."
          />
          <NumberField label="Trigger: rise above rest (g)" value={settings.trigger_deviation_g} onSave={(v) => save({ trigger_deviation_g: v })} />
          <NumberField label="Trigger without free fall (g)" value={settings.trigger_without_freefall_g} onSave={(v) => save({ trigger_without_freefall_g: v })} hint="Higher = less sensitive to handling bumps" />
          <NumberField label="Min. impact peak (g)" value={detector.min_impact_peak_g ?? 2.5} onSave={(v) => saveDetector("min_impact_peak_g", v)} />
          <NumberField label="Free-fall threshold (g)" value={detector.freefall_threshold_g ?? 0.35} onSave={(v) => saveDetector("freefall_threshold_g", v)} />
        </div>
        <div className="mt-3">
          <Toggle checked={!!(detector as Record<string, unknown>).require_freefall} onChange={(v) => saveDetector("require_freefall", v)} label="Require a free-fall phase before a valid impact" />
        </div>
      </Panel>
      <Panel title="Grades 5–8 prediction ranges">
        <NumberRanges value={(settings.prediction_ranges_g as [number, number][]) ?? []} onSave={(v) => save({ prediction_ranges_g: v })} />
      </Panel>
      <Panel title="Restore">
        <p className="text-sm text-slate-400">To restore every setting to the values from the .env file, use System → Restore defaults from .env.</p>
      </Panel>
    </div>
  );
}

function NumberRanges({ value, onSave }: { value: [number, number][]; onSave: (v: [number, number][]) => void }) {
  const [text, setText] = useState(value.map(([a, b]) => `${a}-${b}`).join(", "));
  return (
    <div className="flex items-end gap-2">
      <Field label="Ranges in g" hint="e.g. 0-2, 2-4, 4-6, 6-8, 8-12, 12-16">
        <input className={inputCls} value={text} onChange={(e) => setText(e.target.value)} />
      </Field>
      <Button
        variant="ghost"
        onClick={() =>
          onSave(
            text
              .split(",")
              .map((p) => p.split("-").map((x) => Number(x.trim())) as [number, number])
              .filter(([a, b]) => Number.isFinite(a) && Number.isFinite(b) && b > a),
          )
        }
      >
        Save
      </Button>
    </div>
  );
}


// ---------------------------------------------------------------------------------- system
const MODE_OPTIONS: { value: SensorMode; label: string }[] = [
  { value: "simulation", label: "Simulation" },
  { value: "evb_lite", label: "EVB Lite" },
  { value: "csv_replay", label: "CSV replay" },
];

function EnvHint({ current, envValue, unit = "" }: { current: unknown; envValue: unknown; unit?: string }) {
  if (String(current ?? "") === String(envValue ?? "")) return <span>Same as .env</span>;
  return (
    <span>
      .env value: <code>{envValue === "" || envValue == null ? "(empty)" : `${envValue}${unit}`}</code>
    </span>
  );
}

function SystemTab() {
  const { busy, run } = useAction();
  const notify = useStore((s) => s.notify);
  const lock = useStore((s) => s.lockOperator);
  const refresh = useStore((s) => s.refresh);
  const [view, setView] = useState<SystemView | null>(null);
  const [form, setForm] = useState<SystemSettings | null>(null);
  const [pin1, setPin1] = useState("");
  const [pin2, setPin2] = useState("");

  const load = useCallback(() => {
    api
      .system()
      .then((v) => {
        setView(v);
        setForm(v.settings);
      })
      .catch(() => undefined);
  }, []);
  useEffect(load, [load]);

  if (!view || !form) return <div className="p-6 text-slate-400">Loading…</div>;
  const env = view.env_values;
  const set = <K extends keyof SystemSettings>(k: K, v: SystemSettings[K]) => setForm({ ...form, [k]: v });
  const save = (keys: (keyof SystemSettings)[], msg: string) => {
    const changes: Partial<SystemSettings> = {};
    for (const k of keys) (changes as Record<string, unknown>)[k] = form[k];
    return run(() => api.updateSystem(changes), msg).then((v) => {
      if (v) {
        setView(v);
        setForm(v.settings);
        refresh().catch(() => undefined);
      }
    });
  };
  const changePin = async () => {
    if (pin1.length < 4 || !/^[A-Za-z0-9]+$/.test(pin1)) return notify("error", "PIN must be at least 4 letters or digits.");
    if (pin1 !== pin2) return notify("error", "The two PINs do not match.");
    const ok = await run(() => api.changePin(pin1), "Operator PIN changed");
    if (ok) {
      setOperatorPin(pin1); // keep this browser unlocked
      setPin1("");
      setPin2("");
      load();
    }
  };
  const afterPinReset = () => {
    // The PIN may have changed: ask for it again.
    api.verifyPin().catch(() => {
      lock();
      notify("info", "The operator PIN is back to the .env value — unlock again.");
    });
  };
  const num = (v: string, fallback: number) => (Number.isFinite(Number(v)) && v !== "" ? Number(v) : fallback);

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div className="rounded-xl border border-telemetry/20 bg-telemetry/5 px-4 py-3 text-sm text-slate-300 lg:col-span-2">
        These are the settings from the <code>.env</code> file. You don't need to edit the file: changes made here are saved in the app
        and take effect immediately (they take precedence over <code>.env</code>). Only the port and network access below must be set in{" "}
        <code>.env</code>, because Docker fixes them before the app starts.
      </div>
      {view.config_warnings.map((w) => (
        <div key={w} className="rounded-xl border border-caution/40 bg-caution/10 px-4 py-2 text-sm text-amber-200 lg:col-span-2">
          ⚠ {w}
        </div>
      ))}

      <Panel title="Sensor connection">
        <div className="flex flex-col gap-3">
          <Field label="Sensor mode (SENSOR_MODE)" hint={<EnvHint current={form.sensor_mode} envValue={env.sensor_mode} />}>
            <Segmented value={form.sensor_mode} onChange={(v) => set("sensor_mode", v)} options={MODE_OPTIONS} />
          </Field>
          <div className="grid grid-cols-[1fr_150px] gap-2">
            <Field label="EVB Lite IP address (EVB_HOST)" hint={<EnvHint current={form.evb_host} envValue={env.evb_host} />}>
              <input className={inputCls} value={form.evb_host} placeholder="192.168.1.50" onChange={(e) => set("evb_host", e.target.value)} />
            </Field>
            <Field label="Port (EVB_PORT)" hint={<EnvHint current={form.evb_port} envValue={env.evb_port} />}>
              <input className={inputCls} inputMode="numeric" value={String(form.evb_port)} onChange={(e) => set("evb_port", num(e.target.value, form.evb_port))} />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Request timeout, s (EVB_TIMEOUT_SECONDS)" hint={<EnvHint current={form.evb_timeout_s} envValue={env.evb_timeout_s} unit=" s" />}>
              <input className={inputCls} inputMode="decimal" value={String(form.evb_timeout_s)} onChange={(e) => set("evb_timeout_s", num(e.target.value, form.evb_timeout_s))} />
            </Field>
            <Field label="Sensor range ± g (EVB_ACCEL_RANGE_G)" hint={<EnvHint current={form.evb_accel_range_g} envValue={env.evb_accel_range_g} unit=" g" />}>
              <select className={inputCls} value={String(form.evb_accel_range_g)} onChange={(e) => set("evb_accel_range_g", Number(e.target.value))}>
                {[2, 4, 8, 16, 32, 64, 200].concat([2, 4, 8, 16, 32, 64, 200].includes(form.evb_accel_range_g) ? [] : [form.evb_accel_range_g]).map((g) => (
                  <option key={g} value={g}>
                    ±{g} g{g === 16 ? " (EVB Lite)" : ""}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <p className="text-xs text-slate-500">Use the sensor's IP address, not a .local name. The range must match the range set on the sensor — it is used to detect over-range (saturated) readings.</p>
          <div>
            <Button disabled={busy} onClick={() => save(["sensor_mode", "evb_host", "evb_port", "evb_timeout_s", "evb_accel_range_g"], "Sensor settings saved — reconnecting")}>
              Save sensor settings
            </Button>
          </div>
        </div>
      </Panel>

      <div className="flex flex-col gap-4">
        <Panel title="Operator PIN (OPERATOR_PIN)">
          <div className="mb-3 text-sm text-slate-300">
            Current PIN comes from:{" "}
            {view.operator_pin_source === "dashboard" ? (
              <Badge tone="go">this dashboard</Badge>
            ) : view.operator_pin_source === "env" ? (
              <Badge tone="info">.env (default 1113)</Badge>
            ) : (
              <Badge tone="caution">disabled</Badge>
            )}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Field label="New PIN">
              <input className={`${inputCls} font-mono tracking-widest`} type="password" inputMode="numeric" value={pin1} onChange={(e) => setPin1(e.target.value)} />
            </Field>
            <Field label="Repeat new PIN">
              <input className={`${inputCls} font-mono tracking-widest`} type="password" inputMode="numeric" value={pin2} onChange={(e) => setPin2(e.target.value)} onKeyDown={(e) => e.key === "Enter" && changePin()} />
            </Field>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button disabled={busy || !pin1} onClick={changePin}>
              Change PIN
            </Button>
            {view.operator_pin_source === "dashboard" && (
              <Button variant="ghost" disabled={busy} onClick={() => run(() => api.resetPin(), "PIN reverted to the .env value").then(afterPinReset)}>
                Use the .env PIN again
              </Button>
            )}
          </div>
          <p className="mt-2 text-xs text-slate-500">
            Forgot a PIN set here? On the laptop run <code>docker compose exec app python -m app.cli reset-pin</code>.
          </p>
        </Panel>

        <Panel title="Simulation & logging">
          <div className="grid grid-cols-2 gap-2">
            <Field label="Simulator sample rate, Hz (SIM_SAMPLE_RATE_HZ)" hint={<EnvHint current={form.sim_sample_rate_hz} envValue={env.sim_sample_rate_hz} unit=" Hz" />}>
              <input className={inputCls} inputMode="numeric" value={String(form.sim_sample_rate_hz)} onChange={(e) => set("sim_sample_rate_hz", num(e.target.value, form.sim_sample_rate_hz))} />
            </Field>
            <Field label="Log level (LOG_LEVEL)" hint={<EnvHint current={form.log_level} envValue={env.log_level} />}>
              <select className={inputCls} value={form.log_level} onChange={(e) => set("log_level", e.target.value as SystemSettings["log_level"])}>
                {["DEBUG", "INFO", "WARNING", "ERROR"].map((l) => (
                  <option key={l}>{l}</option>
                ))}
              </select>
            </Field>
          </div>
          <p className="mt-2 text-xs text-slate-500">The reproducible-simulation seed (SIM_SEED) is under Station → Simulation.</p>
          <Button className="mt-3" disabled={busy} onClick={() => save(["sim_sample_rate_hz", "log_level"], "Saved")}>
            Save
          </Button>
        </Panel>
      </div>

      <Panel title="Docker settings (set in .env)">
        <table className="w-full text-sm">
          <tbody>
            <tr className="border-b border-space-700">
              <td className="py-1.5 text-slate-400">Browser port (APP_PORT)</td>
              <td className="py-1.5 text-right font-mono">{view.docker.app_port}</td>
            </tr>
            <tr className="border-b border-space-700">
              <td className="py-1.5 text-slate-400">Network access (APP_BIND)</td>
              <td className="py-1.5 text-right">
                <span className="font-mono">{view.docker.app_bind}</span>{" "}
                <span className="text-slate-500">{view.docker.app_bind === "0.0.0.0" ? "— other devices on the network can connect" : "— this laptop only"}</span>
              </td>
            </tr>
            <tr className="border-b border-space-700">
              <td className="py-1.5 text-slate-400">Test data</td>
              <td className="py-1.5 text-right text-slate-300">Docker volume <code>mission-data</code> ({view.docker.data_dir})</td>
            </tr>
            <tr>
              <td className="py-1.5 text-slate-400">EVB profile file</td>
              <td className="py-1.5 text-right font-mono text-xs">{view.docker.evb_profile_path}</td>
            </tr>
          </tbody>
        </table>
        <p className="mt-2 text-xs text-slate-500">
          To change the port or network access: edit <code>.env</code> next to <code>docker-compose.yml</code>, then run <code>docker compose up -d</code>.
        </p>
      </Panel>

      <Panel title="Restore">
        <p className="mb-3 text-sm text-slate-400">
          Put every setting back to the values from the .env file (or the built-in defaults): sensor, simulation, logging, operator PIN, drop height and analysis thresholds. Test data is not touched.
        </p>
        <Button
          variant="danger"
          disabled={busy}
          onClick={() =>
            run(() => api.restoreSettings(), "Settings restored from .env").then(() => {
              load();
              afterPinReset();
            })
          }
        >
          Restore defaults from .env
        </Button>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------------------- logs
function LogsTab() {
  const [level, setLevel] = useState("WARNING");
  const [logs, setLogs] = useState<LogEntry[]>([]);
  useEffect(() => {
    const load = () => api.logs(level).then(setLogs).catch(() => undefined);
    load();
    const t = window.setInterval(load, 5000);
    return () => window.clearInterval(t);
  }, [level]);
  return (
    <Panel title="Recent events" right={<Segmented size="sm" value={level} onChange={setLevel} options={[{ value: "INFO", label: "All" }, { value: "WARNING", label: "Warnings + errors" }, { value: "ERROR", label: "Errors" }]} />}>
      <div className="max-h-[65vh] overflow-auto font-mono text-xs">
        {logs.map((l, i) => (
          <div key={i} className={`border-b border-space-700 py-1 ${l.level === "ERROR" ? "text-red-300" : l.level === "WARNING" ? "text-amber-200" : "text-slate-300"}`}>
            <span className="text-slate-500">{new Date(l.time).toLocaleTimeString()}</span> [{l.level}] {l.logger}: {l.message}
          </div>
        ))}
        {!logs.length && <div className="p-4 text-slate-500">Nothing to show.</div>}
      </div>
      <p className="mt-2 text-xs text-slate-500">Full logs: /data/logs/mission-mars.log inside the container, or `docker compose logs app`.</p>
    </Panel>
  );
}

// ---------------------------------------------------------------------------------- root
export function OperatorPanel() {
  const open = useStore((s) => s.operatorOpen);
  const unlocked = useStore((s) => s.operatorUnlocked);
  const openOperator = useStore((s) => s.openOperator);
  const lock = useStore((s) => s.lockOperator);
  const refresh = useStore((s) => s.refresh);
  const [tab, setTab] = useState<Tab>("station");
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null);
  const [settingsKey, setSettingsKey] = useState(0);

  const loadSettings = useCallback(() => {
    api
      .settings()
      .then((s) => {
        setSettings(s);
        setSettingsKey((k) => k + 1);
      })
      .catch(() => undefined);
    refresh().catch(() => undefined);
  }, [refresh]);

  useEffect(() => {
    if (open && unlocked) loadSettings();
  }, [open, unlocked, loadSettings]);

  const tabs: { value: Tab; label: string }[] = [
    { value: "station", label: "Station" },
    { value: "system", label: "System" },
    { value: "sensor", label: "Sensor" },
    { value: "gear", label: "Landing gear" },
    { value: "data", label: "Data & export" },
    { value: "analysis", label: "Analysis" },
    { value: "logs", label: "Logs" },
  ];

  return (
    <Modal open={open} onClose={() => openOperator(false)} title="OPERATOR DASHBOARD" wide>
      {!unlocked ? (
        <PinGate />
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Segmented value={tab} onChange={setTab} options={tabs} />
            <Button size="sm" variant="ghost" onClick={lock}>
              🔒 Lock
            </Button>
          </div>
          {tab === "station" && settings && <StationTab key={settingsKey} settings={settings} reload={loadSettings} />}
          {tab === "system" && <SystemTab />}
          {tab === "sensor" && <SensorTab />}
          {tab === "gear" && <GearTab />}
          {tab === "data" && <DataTab />}
          {tab === "analysis" && settings && <AnalysisTab key={settingsKey} settings={settings} reload={loadSettings} />}
          {tab === "logs" && <LogsTab />}
        </div>
      )}
    </Modal>
  );
}

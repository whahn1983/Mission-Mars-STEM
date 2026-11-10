import { useRef, type ReactNode } from "react";
import { SCREENS, useStore, type Screen } from "../state/store";
import { ago } from "../lib/format";

export function SensorChip({ compact = false }: { compact?: boolean }) {
  const sensor = useStore((s) => s.sensor);
  const ws = useStore((s) => s.wsConnected);
  if (!ws) {
    return (
      <span className="inline-flex items-center gap-2 rounded-full border border-alert/50 bg-alert/15 px-3 py-1 text-xs font-bold uppercase tracking-wider text-red-200">
        <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-alert" /> Station offline — reconnecting
      </span>
    );
  }
  if (!sensor) return null;
  const sim = sensor.mode === "simulation";
  const map: Record<string, { tone: string; dot: string; label: string }> = {
    connected: { tone: "border-go/40 bg-go/10 text-green-200", dot: "bg-go", label: "Connected" },
    capturing: { tone: "border-telemetry/50 bg-telemetry/10 text-cyan-100", dot: "bg-telemetry animate-pulse", label: "Capturing" },
    connecting: { tone: "border-caution/40 bg-caution/10 text-amber-200", dot: "bg-caution animate-pulse", label: "Connecting" },
    disconnected: { tone: "border-alert/50 bg-alert/10 text-red-200", dot: "bg-alert", label: "Disconnected" },
    error: { tone: "border-alert/50 bg-alert/10 text-red-200", dot: "bg-alert", label: "Error" },
    not_configured: { tone: "border-caution/40 bg-caution/10 text-amber-200", dot: "bg-caution", label: "Not configured" },
  };
  // A device that answers but has no verified data link must not look ready
  // (green "Connected"): live capture is impossible until the profile exists.
  const noDataLink = sensor.connected && !sensor.streaming && sensor.streaming_available === false;
  const m = noDataLink
    ? { tone: map.not_configured.tone, dot: map.not_configured.dot, label: "Reachable · no data link" }
    : map[sensor.state] ?? map.disconnected;
  const name = sim ? "Simulator" : sensor.mode === "csv_replay" ? "CSV replay" : "EVB Lite";
  return (
    <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-wider ${sim ? "border-sim/50 bg-sim/10 text-purple-100" : m.tone}`}>
      <span className={`h-2.5 w-2.5 rounded-full ${sim ? "bg-sim" : m.dot}`} />
      {name}: {m.label}
      {!compact && sensor.observed_rate_hz && sensor.streaming ? <span className="font-mono normal-case text-slate-300">{Math.round(sensor.observed_rate_hz)} Hz</span> : null}
      {!compact && !sim && !sensor.connected && sensor.last_success_at ? (
        <span className="normal-case text-slate-300">last seen {ago(sensor.seconds_since_success)}</span>
      ) : null}
    </span>
  );
}

export function SimBanner() {
  const sensor = useStore((s) => s.sensor);
  if (!sensor || sensor.data_origin === "physical") return null;
  const text =
    sensor.data_origin === "simulated"
      ? "SIMULATION MODE — SIMULATED DATA, NOT A PHYSICAL MEASUREMENT"
      : "REPLAY MODE — RECORDED DATA, PROVENANCE NOT VERIFIED";
  return (
    <div className="sim-stripes border-b border-sim/40 py-1 text-center font-display text-[11px] font-bold tracking-[0.25em] text-purple-100">
      {text}
    </div>
  );
}

function Steps() {
  const screen = useStore((s) => s.screen);
  const idx = SCREENS.findIndex((s) => s.id === screen);
  return (
    <ol className="hidden items-center gap-1 lg:flex">
      {SCREENS.map((s, i) => (
        <li key={s.id} className="flex items-center gap-1">
          <span
            className={`rounded-full px-3 py-1 text-[11px] font-bold uppercase tracking-widest ${
              i === idx ? "bg-telemetry text-space-950" : i < idx ? "bg-telemetry/15 text-telemetry" : "bg-space-800 text-slate-500"
            }`}
          >
            {s.label}
          </span>
          {i < SCREENS.length - 1 && <span className={`h-px w-4 ${i < idx ? "bg-telemetry/60" : "bg-space-600"}`} />}
        </li>
      ))}
    </ol>
  );
}

export function Brand({ onSecretPress }: { onSecretPress?: () => void }) {
  const timer = useRef<number | null>(null);
  // Long-press the logo for 2 s to open the operator dashboard (touchscreens).
  const start = () => {
    if (!onSecretPress) return;
    timer.current = window.setTimeout(onSecretPress, 2000);
  };
  const cancel = () => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = null;
  };
  return (
    <div className="flex items-center gap-3" onPointerDown={start} onPointerUp={cancel} onPointerLeave={cancel}>
      <svg viewBox="0 0 64 64" className="h-10 w-10 shrink-0" aria-hidden>
        <circle cx="32" cy="32" r="18" fill="#f97316" />
        <circle cx="26" cy="27" r="4" fill="#c2410c" />
        <circle cx="38" cy="38" r="3" fill="#c2410c" />
        <ellipse cx="32" cy="32" rx="29" ry="9" fill="none" stroke="#22d3ee" strokeWidth="2.5" transform="rotate(-20 32 32)" />
      </svg>
      <div className="leading-tight">
        <div className="font-display text-xl font-black tracking-[0.3em] text-white">MISSION MARS</div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.28em] text-telemetry/80">Lander Engineering Laboratory</div>
      </div>
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const openOperator = useStore((s) => s.openOperator);
  const screen = useStore((s) => s.screen);
  const go = useStore((s) => s.go);
  const toast = useStore((s) => s.toast);

  const fullscreen = () => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => undefined);
    else document.documentElement.requestFullscreen().catch(() => undefined);
  };

  return (
    <div className="bg-mission flex h-full flex-col overflow-hidden">
      <SimBanner />
      <header className="flex items-center justify-between gap-4 border-b border-telemetry/10 px-5 py-3">
        <button type="button" className="text-left" onClick={() => screen !== "test" && go("briefing" as Screen)}>
          <Brand onSecretPress={() => openOperator(true)} />
        </button>
        <Steps />
        <div className="flex items-center gap-2">
          <SensorChip />
          <button type="button" onClick={fullscreen} className="rounded-lg px-2 py-1 text-slate-500 hover:bg-space-700 hover:text-slate-200" title="Full screen" aria-label="Full screen">
            ⛶
          </button>
          <button
            type="button"
            onClick={() => openOperator(true)}
            className="rounded-lg px-2 py-1 text-slate-600 hover:bg-space-700 hover:text-slate-200"
            title="Operator dashboard (Ctrl+Shift+O)"
            aria-label="Operator dashboard"
          >
            ⚙
          </button>
        </div>
      </header>
      <main className="relative min-h-0 flex-1 overflow-auto">{children}</main>
      {toast && (
        <div
          key={toast.id}
          className={`pop-in fixed bottom-6 left-1/2 z-[60] -translate-x-1/2 rounded-2xl border px-6 py-3 text-base font-semibold shadow-2xl ${
            toast.kind === "error" ? "border-alert/60 bg-red-950/95 text-red-100" : toast.kind === "success" ? "border-go/60 bg-green-950/95 text-green-100" : "border-telemetry/50 bg-space-800/95 text-cyan-50"
          }`}
        >
          {toast.text}
        </div>
      )}
    </div>
  );
}

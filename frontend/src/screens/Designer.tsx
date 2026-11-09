import { useEffect, useState } from "react";
import type { Configuration } from "../api/types";
import { Badge, Button, Panel, TraitBar } from "../components/ui";
import { TRAIT_LABELS } from "../lib/copy";
import { fmtHeight, fmtMass } from "../lib/format";
import { useStore } from "../state/store";
import { LanderScene } from "../three/LanderScene";

const G = 9.80665;

function GearCard({ c, selected, onClick, index }: { c: Configuration; selected: boolean; onClick: () => void; index: number }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-4 rounded-2xl border-2 p-3 text-left transition ${
        selected ? "border-telemetry bg-telemetry/10 shadow-[0_0_30px_-10px_rgba(34,211,238,0.9)]" : "border-space-600 bg-space-800/60 hover:border-telemetry/40"
      }`}
    >
      <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl font-display text-2xl font-black text-space-950" style={{ background: c.display_color }}>
        {c.code}
      </div>
      {c.photo_url && <img src={c.photo_url} alt="" className="h-14 w-14 shrink-0 rounded-lg object-cover" />}
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xl font-bold text-white">{c.name}</span>
          <span className="font-mono text-sm text-slate-400">{fmtMass(c.mass_kg)}</span>
        </div>
        <div className="truncate text-sm text-slate-400">{c.material}</div>
      </div>
      <kbd className="hidden rounded border border-space-500 px-1.5 text-xs text-slate-500 md:block">{index + 1}</kbd>
    </button>
  );
}

export function Designer() {
  const configs = useStore((s) => s.configurations);
  const configurationId = useStore((s) => s.configurationId);
  const select = useStore((s) => s.selectConfiguration);
  const go = useStore((s) => s.go);
  const settings = useStore((s) => s.settings);
  const sensor = useStore((s) => s.sensor);
  const gradeBand = useStore((s) => s.gradeBand);
  const dropHeight = useStore((s) => s.dropHeight);
  const setDropHeight = useStore((s) => s.setDropHeight);
  const [xray, setXray] = useState(false);
  const [spin, setSpin] = useState(true);

  const enabled = configs.filter((c) => c.enabled);
  const selected = enabled.find((c) => c.id === configurationId) ?? null;

  useEffect(() => {
    if (!selected && enabled.length) select(enabled[0].id);
  }, [selected, enabled, select]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      const n = Number(e.key);
      if (n >= 1 && n <= enabled.length) select(enabled[n - 1].id);
      if (e.key.toLowerCase() === "x") setXray((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled, select]);

  const sim = sensor?.mode === "simulation";
  const canChangeHeight = sim && settings?.allow_student_height_change;
  const height = (canChangeHeight && dropHeight) || settings?.drop_height_m || 0.2;
  const budget = settings?.criteria.mass_budget_kg ?? 0.35;
  const mass = selected?.mass_kg ?? 0;
  const massPct = Math.min(130, (mass / budget) * 100);
  const overBudget = mass > budget;
  const speed = Math.sqrt(2 * G * height);
  const energy = mass * G * height;
  const traits = selected?.parameters_json.traits ?? {};

  return (
    <div className="grid min-h-full grid-cols-1 gap-5 p-5 xl:h-full xl:grid-cols-[1.4fr_1fr]">
      <div className="panel relative min-h-[460px] overflow-hidden p-0">
        <LanderScene geometry={selected?.parameters_json.geometry} accent={selected?.display_color} xray={xray} autoRotate={spin} />
        <div className="absolute left-4 top-4 flex flex-col gap-1">
          <div className="font-display text-xs tracking-[0.3em] text-telemetry/80">LANDER DESIGNER · CAD VIEW</div>
          <div className="text-3xl font-black text-white">
            {selected ? (
              <>
                <span style={{ color: selected.display_color }}>{selected.code}</span> · {selected.name}
              </>
            ) : (
              "Choose landing gear"
            )}
          </div>
        </div>
        <div className="absolute bottom-4 left-4 flex flex-wrap gap-2">
          <Button variant={xray ? "primary" : "ghost"} size="sm" onClick={() => setXray((v) => !v)}>
            {xray ? "◉" : "○"} X-ray: view sensor payload
          </Button>
          <Button variant={spin ? "primary" : "ghost"} size="sm" onClick={() => setSpin((v) => !v)}>
            ⟳ Auto-rotate
          </Button>
        </div>
        <div className="pointer-events-none absolute bottom-4 right-4 text-right text-xs text-slate-400">
          Drag to rotate · Pinch or scroll to zoom
        </div>
        {xray && (
          <div className="pointer-events-none absolute right-4 top-4 max-w-xs rounded-xl border border-telemetry/40 bg-space-950/80 p-3 text-sm text-cyan-100">
            <b>Science payload:</b> a 3-axis accelerometer (41 × 37 × 19 mm) bolted to the center of the lander. It measures how hard the landing shakes it.
          </div>
        )}
      </div>

      <div className="flex flex-col gap-4 [&>*]:shrink-0 xl:min-h-0 xl:overflow-auto">
        <Panel title="1 · Choose your landing gear">
          <div className="flex flex-col gap-2">
            {enabled.map((c, i) => (
              <GearCard key={c.id} c={c} index={i} selected={c.id === selected?.id} onClick={() => select(c.id)} />
            ))}
            {!enabled.length && <div className="text-slate-400">No landing-gear configurations are enabled. Ask the operator.</div>}
          </div>
        </Panel>

        {selected && (
          <Panel title="2 · Engineering trade-offs">
            <p className={`mb-3 text-slate-300 ${gradeBand === "k4" ? "text-lg" : ""}`}>{selected.description}</p>
            <div className="grid grid-cols-2 gap-x-6 gap-y-2">
              {Object.entries(traits).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between gap-3">
                  <span className="text-sm text-slate-300">{TRAIT_LABELS[k] ?? k}</span>
                  <TraitBar value={v} color={k === "rebound" ? "#f59e0b" : selected.display_color === "#f8fafc" ? "#22d3ee" : selected.display_color} />
                </div>
              ))}
            </div>
            <div className="mt-4">
              <div className="mb-1 flex justify-between text-sm">
                <span className="text-slate-300">Mass budget</span>
                <span className={`font-mono ${overBudget ? "text-red-300" : "text-green-300"}`}>
                  {fmtMass(mass)} / {fmtMass(budget)}
                </span>
              </div>
              <div className="relative h-4 overflow-hidden rounded-full bg-space-700">
                <div className={`h-full rounded-full ${overBudget ? "bg-alert" : "bg-go"}`} style={{ width: `${Math.min(100, massPct)}%` }} />
              </div>
              {overBudget && <div className="mt-1 text-sm text-red-300">Over the mass budget — heavier landers cost more fuel.</div>}
            </div>
          </Panel>
        )}

        <Panel title="3 · Landing conditions" right={sim ? <Badge tone="sim">simulation</Badge> : <Badge tone="go">physical test</Badge>}>
          {canChangeHeight ? (
            <div className="mb-3 flex flex-wrap gap-2">
              {(settings?.drop_height_options_m ?? [0.1, 0.2, 0.3]).map((h) => (
                <Button key={h} size="sm" variant={Math.abs(h - height) < 1e-6 ? "primary" : "ghost"} onClick={() => setDropHeight(h)}>
                  {fmtHeight(h)}
                </Button>
              ))}
            </div>
          ) : (
            <div className="mb-3 text-sm text-slate-400">Drop height is set by the operator for the physical test stand.</div>
          )}
          <div className="grid grid-cols-3 gap-2">
            <div className="rounded-xl bg-space-850/70 p-2 text-center">
              <div className="text-[11px] uppercase tracking-widest text-slate-400">Drop height</div>
              <div className="font-mono text-2xl font-bold text-white">{fmtHeight(height)}</div>
            </div>
            {gradeBand !== "k4" && (
              <>
                <div className="rounded-xl bg-space-850/70 p-2 text-center">
                  <div className="text-[11px] uppercase tracking-widest text-slate-400">Impact speed</div>
                  <div className="font-mono text-2xl font-bold text-white">{speed.toFixed(2)}</div>
                  <div className="text-[11px] text-slate-500">m/s · v = √(2gh)</div>
                </div>
                <div className="rounded-xl bg-space-850/70 p-2 text-center">
                  <div className="text-[11px] uppercase tracking-widest text-slate-400">Energy</div>
                  <div className="font-mono text-2xl font-bold text-white">{energy.toFixed(2)}</div>
                  <div className="text-[11px] text-slate-500">J · E = mgh</div>
                </div>
              </>
            )}
          </div>
          {gradeBand !== "k4" && <div className="mt-2 text-xs text-slate-500">Simplified Earth-gravity classroom calculation (no air drag). The test happens on Earth.</div>}
        </Panel>

        <Button variant="mars" size="lg" disabled={!selected} onClick={() => go("predict")} className="font-display tracking-[0.2em]">
          NEXT: MAKE A PREDICTION ▶
        </Button>
      </div>
    </div>
  );
}

import { useState } from "react";
import { Button } from "../components/ui";
import { BRIEFING, DESCENT_STEPS, fmtScaledHeight, GRADE_BANDS, MODEL_SCALE, numberWord } from "../lib/copy";
import { fmtHeight } from "../lib/format";
import { heightOptions } from "../lib/height";
import { useStore } from "../state/store";
import type { DescentPhase } from "../three/Lander";
import { LanderScene } from "../three/LanderScene";

const REQ_ICONS = [
  // payload shield
  <svg key="a" viewBox="0 0 64 64" className="h-14 w-14"><path d="M32 6 52 14v16c0 14-9 23-20 28C21 53 12 44 12 30V14Z" fill="#0e7490" stroke="#22d3ee" strokeWidth="3" /><rect x="23" y="25" width="18" height="12" rx="2" fill="#0f172a" stroke="#22d3ee" strokeWidth="2" /><circle cx="37" cy="29" r="2" fill="#22c55e" /></svg>,
  // soft landing
  <svg key="b" viewBox="0 0 64 64" className="h-14 w-14"><path d="M8 52h48" stroke="#f97316" strokeWidth="4" strokeLinecap="round" /><path d="M20 40h24l-4-14H24Z" fill="#e5e7eb" /><path d="M22 40l-6 10M42 40l6 10" stroke="#cbd5e1" strokeWidth="3" /><path d="M14 18c4-4 8 4 12 0s8 4 12 0 8 4 12 0" stroke="#22d3ee" strokeWidth="3" fill="none" strokeLinecap="round" /></svg>,
  // mass budget
  <svg key="c" viewBox="0 0 64 64" className="h-14 w-14"><path d="M32 10v40M14 50h36" stroke="#cbd5e1" strokeWidth="3" strokeLinecap="round" /><path d="M10 22h44" stroke="#cbd5e1" strokeWidth="3" strokeLinecap="round" /><path d="M10 22 4 36h12ZM54 22l-6 14h12Z" fill="#f97316" opacity="0.85" /><circle cx="32" cy="10" r="4" fill="#22d3ee" /></svg>,
];

export function Briefing() {
  const gradeBand = useStore((s) => s.gradeBand);
  const setGradeBand = useStore((s) => s.setGradeBand);
  const go = useStore((s) => s.go);
  const settings = useStore((s) => s.settings);
  const legKinds = useStore((s) => s.configurations.filter((c) => c.enabled).length);
  const [phase, setPhase] = useState<DescentPhase>("descent");
  const copy = BRIEFING[gradeBand];
  const young = gradeBand === "k4";
  const heights = heightOptions(settings);
  const legsLine = legKinds
    ? `${young ? "Try" : "Test"} ${numberWord(legKinds)} kinds of landing legs. Which one lands the softest?`
    : "Which landing legs land the softest?";

  return (
    <div className="grid min-h-full grid-cols-1 gap-6 p-6 xl:h-full xl:grid-cols-[1.05fr_1fr]">
      <div className="flex min-h-0 flex-col justify-center-safe gap-5">
        <div>
          <div className="mb-2 font-display text-sm tracking-[0.4em] text-mars">MISSION BRIEFING</div>
          <h1 className="font-display text-4xl font-black leading-tight text-white xl:text-6xl">
            Design it. <span className="text-telemetry glow-cyan">Test it.</span> <span className="text-mars glow-mars">Improve it.</span>
          </h1>
          <p className={`mt-4 max-w-2xl text-slate-200 ${young ? "text-3xl font-semibold" : "text-2xl"}`}>{copy.lead}</p>
          <p className={`mt-2 max-w-2xl text-slate-400 ${young ? "text-xl" : "text-lg"}`}>{copy.body}</p>
        </div>

        <div className="panel p-4">
          <div className="mb-1 text-xs font-bold uppercase tracking-[0.25em] text-mars">The landing plan</div>
          <p className={`text-slate-200 ${young ? "text-lg" : "text-base"}`}>{copy.story}</p>
          <p className="mt-3 text-sm text-slate-400">{copy.scale}</p>
          <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-3">
            {heights.map((h) => (
              <div key={h} className="flex items-baseline gap-2 rounded-xl border border-telemetry/30 bg-space-850/70 px-4 py-1.5" title={`1:${MODEL_SCALE} scale`}>
                <span className="font-display text-xl font-black text-white">{fmtScaledHeight(h)}</span>
                <span className="font-mono text-sm text-slate-400">({fmtHeight(h)})</span>
              </div>
            ))}
            <p className={`font-semibold text-telemetry sm:ml-2 ${young ? "text-lg" : "text-sm"}`}>{legsLine}</p>
          </div>
        </div>

        <div>
          <div className="mb-2 text-xs font-bold uppercase tracking-[0.25em] text-slate-400">Who is flying today?</div>
          <div className="flex flex-wrap gap-3">
            {GRADE_BANDS.map((g) => (
              <button
                key={g.id}
                type="button"
                onClick={() => setGradeBand(g.id)}
                className={`rounded-2xl border-2 px-5 py-3 text-left transition ${
                  gradeBand === g.id ? "border-telemetry bg-telemetry/15 shadow-[0_0_30px_-8px_rgba(34,211,238,0.8)]" : "border-space-600 bg-space-800/70 hover:border-telemetry/50"
                }`}
              >
                <div className="text-lg font-bold text-white">
                  <span className="mr-2">{g.icon}</span>
                  {g.label}
                </div>
                <div className="text-xs font-semibold uppercase tracking-widest text-telemetry/80">{g.title}</div>
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {copy.reqs.map((r, i) => (
            <div key={r.title} className="panel flex flex-col gap-2 p-4">
              <div className="flex items-center gap-3">
                {REQ_ICONS[i]}
                <span className="font-display text-3xl font-black text-telemetry/40">{i + 1}</span>
              </div>
              <div className={`font-bold text-white ${young ? "text-2xl" : "text-lg"}`}>{r.title}</div>
              <div className={`text-slate-400 ${young ? "text-lg" : "text-sm"}`}>{r.body}</div>
            </div>
          ))}
        </div>

        <div className="flex items-center gap-4">
          <Button variant="mars" size="xl" onClick={() => go("design")} className="font-display tracking-[0.2em]">
            START MISSION ▶
          </Button>
          <span className="text-sm text-slate-500">Press Enter</span>
        </div>
      </div>

      <div className="panel relative min-h-[420px] overflow-hidden p-0">
        <LanderScene mode="descent" interactive={false} autoRotate={false} cameraDistance={1.45} onPhase={setPhase} />
        <div className="pointer-events-none absolute left-4 top-4 font-mono text-xs leading-5 text-telemetry/70">
          <div>TARGET: JEZERO-ANALOG TEST SITE</div>
          <div>PAYLOAD: 3-AXIS ACCELEROMETER</div>
        </div>
        <ol className="pointer-events-none absolute inset-x-3 bottom-3 flex flex-wrap justify-center gap-1.5" aria-label="Landing sequence">
          {DESCENT_STEPS.map((step, i) => {
            const active = step.id === phase;
            return (
              <li
                key={step.id}
                aria-current={active ? "step" : undefined}
                className={`rounded-full border px-2.5 py-1 font-display text-[10px] font-bold uppercase tracking-[0.12em] transition-colors duration-200 2xl:px-3 2xl:text-[11px] 2xl:tracking-[0.18em] ${
                  active ? "border-mars bg-mars/25 text-white shadow-[0_0_20px_-6px_rgba(249,115,22,0.9)]" : "border-space-600 bg-space-900/70 text-slate-500"
                }`}
              >
                {i + 1} · {young && "young" in step ? step.young : step.label}
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}

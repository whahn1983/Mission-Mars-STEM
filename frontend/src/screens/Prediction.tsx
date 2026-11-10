import { useEffect, useState } from "react";
import { Button, Panel } from "../components/ui";
import { categoryOptions, numberPrediction, rangeOptions, type PredictionOption } from "../lib/predict";
import { useStore } from "../state/store";

const CATEGORY_ART: Record<string, { emoji: string; color: string; text: string }> = {
  gentle: { emoji: "🪶", color: "#22c55e", text: "Like a feather" },
  medium: { emoji: "🏀", color: "#f59e0b", text: "Like a bouncing ball" },
  hard: { emoji: "🪨", color: "#ef4444", text: "Like a dropped rock" },
};

function OptionGrid({ options, selectedKey, onPick, big }: { options: PredictionOption[]; selectedKey: string | null; onPick: (o: PredictionOption) => void; big?: boolean }) {
  return (
    <div className={`grid gap-4 ${big ? "grid-cols-1 md:grid-cols-3" : "grid-cols-2 md:grid-cols-4"}`}>
      {options.map((o, i) => {
        const art = CATEGORY_ART[o.key];
        const sel = selectedKey === o.key;
        return (
          <button
            key={o.key}
            type="button"
            onClick={() => onPick(o)}
            className={`rounded-3xl border-4 p-5 text-center transition active:scale-95 ${sel ? "border-telemetry bg-telemetry/15 shadow-[0_0_40px_-10px_rgba(34,211,238,0.9)]" : "border-space-600 bg-space-800/70 hover:border-telemetry/40"}`}
          >
            {art && <div className={`${big ? "text-8xl" : "text-5xl"}`}>{art.emoji}</div>}
            <div className={`mt-2 font-display font-black text-white ${big ? "text-4xl" : "text-2xl"}`} style={art ? { color: art.color } : undefined}>
              {o.label}
            </div>
            {art && <div className="mt-1 text-lg text-slate-300">{art.text}</div>}
            {o.sub && <div className="mt-1 text-sm text-slate-400">{o.sub}</div>}
            <kbd className="mt-2 inline-block rounded border border-space-500 px-1.5 text-xs text-slate-500">{i + 1}</kbd>
          </button>
        );
      })}
    </div>
  );
}

function Keypad({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const press = (k: string) => {
    if (k === "⌫") return onChange(value.slice(0, -1));
    if (k === "." && value.includes(".")) return;
    if (value.length >= 5) return;
    onChange(value + k);
  };
  return (
    <div className="grid w-full max-w-xs grid-cols-3 gap-3">
      {["7", "8", "9", "4", "5", "6", "1", "2", "3", ".", "0", "⌫"].map((k) => (
        <button key={k} type="button" onClick={() => press(k)} className="rounded-2xl border border-space-500 bg-space-800 py-4 font-mono text-3xl font-bold text-white hover:bg-space-700 active:scale-95">
          {k}
        </button>
      ))}
    </div>
  );
}

export function Prediction() {
  const gradeBand = useStore((s) => s.gradeBand);
  const settings = useStore((s) => s.settings);
  const prediction = useStore((s) => s.prediction);
  const setPrediction = useStore((s) => s.setPrediction);
  const go = useStore((s) => s.go);
  const configs = useStore((s) => s.configurations);
  const configurationId = useStore((s) => s.configurationId);
  const cfg = configs.find((c) => c.id === configurationId);
  const [num, setNum] = useState(prediction?.kind === "number" && prediction.value_g != null ? String(prediction.value_g) : "");

  const criteria = settings?.criteria;
  const options =
    gradeBand === "k4" && criteria ? categoryOptions(criteria) : gradeBand === "58" ? rangeOptions(settings?.prediction_ranges_g ?? []) : [];
  const selectedKey = prediction && prediction.kind !== "number" ? options.find((o) => o.payload.label === prediction.label)?.key ?? null : null;

  useEffect(() => {
    if (gradeBand !== "912") return;
    const v = parseFloat(num);
    if (Number.isFinite(v) && v >= 0 && v < 1000) setPrediction(numberPrediction(Math.round(v * 10) / 10));
    else if (num === "") setPrediction(null);
  }, [num, gradeBand, setPrediction]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      if (gradeBand !== "912") {
        const n = Number(e.key);
        if (n >= 1 && n <= options.length) setPrediction(options[n - 1].payload);
      } else if (/^[0-9.]$/.test(e.key)) setNum((v) => (v.length < 5 ? v + e.key : v));
      else if (e.key === "Backspace") setNum((v) => v.slice(0, -1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [gradeBand, options, setPrediction]);

  const question = gradeBand === "k4" ? "How hard will the landing be?" : "How many g's will your lander experience?";
  const help =
    gradeBand === "k4"
      ? "Sitting still feels like 1 g. A big bump might feel like 10 g!"
      : gradeBand === "58"
        ? "1 g is what you feel standing still. Pick the range you think the peak landing shock will fall in."
        : "Predict the peak specific force (vector magnitude, in g) measured at the payload. At rest the sensor reads 1 g.";

  return (
    <div className="mx-auto flex h-full max-w-6xl flex-col justify-center gap-6 p-6">
      <div className="text-center">
        <div className="mb-2 font-display text-sm tracking-[0.4em] text-mars">PREDICTION</div>
        <h1 className={`font-display font-black text-white ${gradeBand === "k4" ? "text-5xl" : "text-4xl"}`}>{question}</h1>
        <p className="mx-auto mt-3 max-w-3xl text-xl text-slate-300">{help}</p>
        {cfg && (
          <p className="mt-2 text-slate-400">
            Design: <b style={{ color: cfg.display_color }}>{cfg.code} · {cfg.name}</b>
          </p>
        )}
      </div>

      {gradeBand === "912" ? (
        <Panel className="mx-auto flex w-full max-w-3xl flex-col items-center gap-5 p-6 md:flex-row md:items-start md:justify-center">
          <div className="flex flex-col items-center gap-3">
            <div className="flex items-baseline gap-2 rounded-2xl border-2 border-telemetry/50 bg-space-950 px-6 py-4">
              <input
                value={num}
                onChange={(e) => setNum(e.target.value.replace(/[^0-9.]/g, "").slice(0, 5))}
                inputMode="decimal"
                placeholder="0.0"
                className="w-44 bg-transparent text-right font-mono text-6xl font-bold text-white outline-none"
                aria-label="Predicted peak acceleration in g"
              />
              <span className="font-mono text-4xl text-telemetry">g</span>
            </div>
            <input
              type="range"
              min={0}
              max={Math.max(30, Math.ceil(Number(num) || 0))}
              step={0.5}
              value={Number(num) || 0}
              onChange={(e) => setNum(e.target.value)}
              className="w-72 accent-cyan-400"
              aria-label="Prediction slider"
            />
          </div>
          <Keypad value={num} onChange={setNum} />
        </Panel>
      ) : (
        <OptionGrid options={options} selectedKey={selectedKey} onPick={(o) => setPrediction(o.payload)} big={gradeBand === "k4"} />
      )}

      <div className="flex items-center justify-center gap-4">
        <Button variant="ghost" size="lg" onClick={() => go("design")}>
          ◀ Back
        </Button>
        <Button variant="mars" size="lg" disabled={!prediction} onClick={() => go("test")} className="font-display tracking-[0.2em]">
          GO TO TEST STAND ▶
        </Button>
      </div>
    </div>
  );
}

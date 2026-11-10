import type { Criteria, GradeBand, PredictionPayload } from "../api/types";

export interface PredictionOption {
  key: string;
  label: string;
  sub: string;
  payload: PredictionPayload;
}

export function categoryOptions(c: Criteria): PredictionOption[] {
  return [
    { key: "gentle", label: "Gentle", sub: `less than ${c.gentle_max_g} g`, payload: { kind: "category", label: "Gentle", low_g: 0, high_g: c.gentle_max_g } },
    { key: "medium", label: "Medium", sub: `${c.gentle_max_g}–${c.medium_max_g} g`, payload: { kind: "category", label: "Medium", low_g: c.gentle_max_g, high_g: c.medium_max_g } },
    { key: "hard", label: "Hard", sub: `more than ${c.medium_max_g} g`, payload: { kind: "category", label: "Hard", low_g: c.medium_max_g, high_g: null } },
  ];
}

export function rangeOptions(ranges: [number, number][]): PredictionOption[] {
  const opts: PredictionOption[] = ranges.map(([lo, hi]) => ({
    key: `${lo}-${hi}`,
    label: `${lo}–${hi} g`,
    sub: "",
    payload: { kind: "range" as const, label: `${lo}–${hi} g`, low_g: lo, high_g: hi },
  }));
  const top = ranges.length ? ranges[ranges.length - 1][1] : 16;
  opts.push({ key: `${top}+`, label: `${top}+ g`, sub: "", payload: { kind: "range", label: `${top}+ g`, low_g: top, high_g: null } });
  return opts;
}

export function numberPrediction(value: number): PredictionPayload {
  return { kind: "number", label: `${value} g`, value_g: value };
}

export function describePrediction(p: PredictionPayload | null): string {
  if (!p) return "No prediction";
  if (p.kind === "number") return `${p.value_g} g`;
  return p.label ?? "—";
}

export function predictionVerdict(
  p: PredictionPayload | null,
  measured: number | null,
  band: GradeBand,
): { text: string; good: boolean } | null {
  if (!p || measured === null) return null;
  if (p.kind === "number" && p.value_g !== null && p.value_g !== undefined) {
    const err = measured - p.value_g;
    const close = Math.abs(err) <= Math.max(1, 0.15 * measured);
    if (band === "912") {
      const pct = measured ? (Math.abs(err) / measured) * 100 : 0;
      return { text: `${close ? "Close!" : "Off by"} ${Math.abs(err).toFixed(1)} g (${pct.toFixed(0)}% ${err > 0 ? "higher" : "lower"} than predicted)`, good: close };
    }
    return { text: close ? "Great prediction!" : `It was ${err > 0 ? "harder" : "softer"} than you predicted.`, good: close };
  }
  const lo = p.low_g ?? 0;
  const hi = p.high_g ?? Infinity;
  const inside = measured >= lo && measured < hi;
  if (inside) return { text: band === "k4" ? "You predicted it right!" : "Your prediction range was correct!", good: true };
  return { text: measured >= hi ? "It was harder than you predicted." : "It was gentler than you predicted.", good: false };
}

export function measuredCategory(measured: number, c: Criteria): string {
  if (measured < c.gentle_max_g) return "Gentle";
  if (measured < c.medium_max_g) return "Medium";
  return "Hard";
}

export const fmtG = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined || !Number.isFinite(v) ? "—" : `${v.toFixed(digits)} g`;

export const fmtNum = (v: number | null | undefined, digits = 1, unit = "") =>
  v === null || v === undefined || !Number.isFinite(v) ? "—" : `${v.toFixed(digits)}${unit ? ` ${unit}` : ""}`;

export const fmtHeight = (m: number | null | undefined) =>
  m === null || m === undefined ? "—" : `${Math.round(m * 100)} cm`;

export const fmtMass = (kg: number | null | undefined) =>
  kg === null || kg === undefined ? "—" : `${Math.round(kg * 1000)} g`;

export const fmtTime = (iso: string | null | undefined) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
};

export const fmtDateTime = (iso: string | null | undefined) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
};

export const ago = (seconds: number | null | undefined) => {
  if (seconds === null || seconds === undefined) return "never";
  if (seconds < 2) return "just now";
  if (seconds < 60) return `${Math.round(seconds)} s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  return `${Math.round(seconds / 3600)} h ago`;
};

export const ORIGIN_LABEL: Record<string, string> = {
  physical: "Measured by sensor",
  simulated: "SIMULATED DATA — NOT A PHYSICAL MEASUREMENT",
  unverified: "IMPORTED DATA — PROVENANCE NOT VERIFIED",
};

export const SOURCE_LABEL: Record<string, string> = {
  simulation: "Simulation",
  evb_lite: "EVB Lite sensor",
  csv_replay: "CSV replay",
  csv_import: "CSV import",
};

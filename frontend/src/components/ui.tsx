import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "mars" | "go" | "ghost" | "danger" | "caution" | "sim";
type Size = "sm" | "md" | "lg" | "xl";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-telemetry/90 text-space-950 hover:bg-telemetry shadow-[0_0_30px_-6px_rgba(34,211,238,0.7)] disabled:bg-space-600 disabled:text-slate-400 disabled:shadow-none",
  mars: "bg-mars text-space-950 hover:bg-orange-400 shadow-[0_0_34px_-6px_rgba(249,115,22,0.8)] disabled:bg-space-600 disabled:text-slate-400 disabled:shadow-none",
  go: "bg-go text-space-950 hover:bg-green-400 shadow-[0_0_30px_-6px_rgba(34,197,94,0.7)] disabled:bg-space-600 disabled:text-slate-400 disabled:shadow-none",
  ghost: "bg-space-700/70 text-slate-100 hover:bg-space-600 border border-telemetry/20 disabled:opacity-40",
  danger: "bg-alert/90 text-white hover:bg-alert disabled:opacity-40",
  caution: "bg-caution text-space-950 hover:bg-amber-400 disabled:opacity-40",
  sim: "bg-sim text-space-950 hover:bg-purple-300 shadow-[0_0_34px_-6px_rgba(192,132,252,0.8)] disabled:bg-space-600 disabled:text-slate-400 disabled:shadow-none",
};

const SIZES: Record<Size, string> = {
  sm: "px-3 py-1.5 text-sm rounded-lg",
  md: "px-5 py-2.5 text-base rounded-xl",
  lg: "px-7 py-4 text-lg rounded-2xl",
  xl: "px-10 py-6 text-2xl rounded-3xl",
};

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
  return (
    <button
      type="button"
      className={`font-semibold tracking-wide transition active:scale-[0.97] disabled:cursor-not-allowed focus:outline-none focus-visible:ring-4 focus-visible:ring-telemetry/50 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

export function Panel({ title, right, className = "", children }: { title?: ReactNode; right?: ReactNode; className?: string; children: ReactNode }) {
  return (
    <section className={`panel p-4 ${className}`}>
      {(title || right) && (
        <header className="mb-3 flex items-center justify-between gap-3">
          {title ? <h3 className="panel-title">{title}</h3> : <span />}
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

export function Badge({ tone = "info", children, className = "" }: { tone?: "info" | "go" | "caution" | "alert" | "sim" | "mars" | "muted"; children: ReactNode; className?: string }) {
  const tones = {
    info: "bg-telemetry/15 text-telemetry border-telemetry/40",
    go: "bg-go/15 text-green-300 border-go/40",
    caution: "bg-caution/15 text-amber-300 border-caution/40",
    alert: "bg-alert/15 text-red-300 border-alert/50",
    sim: "bg-sim/15 text-purple-200 border-sim/50",
    mars: "bg-mars/15 text-orange-300 border-mars/40",
    muted: "bg-space-700 text-slate-300 border-space-500",
  } as const;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wider ${tones[tone]} ${className}`}>
      {children}
    </span>
  );
}

export function Stat({ label, value, sub, tone = "default" }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "default" | "go" | "caution" | "alert" | "mars" }) {
  const tones = { default: "text-slate-50", go: "text-green-300", caution: "text-amber-300", alert: "text-red-300", mars: "text-orange-300" };
  return (
    <div className="rounded-xl border border-telemetry/10 bg-space-850/70 px-3 py-2">
      <div className="text-[11px] font-semibold uppercase tracking-widest text-slate-400">{label}</div>
      <div className={`font-mono text-xl font-bold ${tones[tone]}`}>{value}</div>
      {sub && <div className="text-xs text-slate-400">{sub}</div>}
    </div>
  );
}

export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label?: ReactNode; disabled?: boolean }) {
  return (
    <label className={`inline-flex cursor-pointer items-center gap-3 ${disabled ? "opacity-40" : ""}`}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative h-7 w-12 rounded-full transition ${checked ? "bg-go" : "bg-space-600"}`}
      >
        <span className={`absolute top-1 h-5 w-5 rounded-full bg-white transition-all ${checked ? "left-6" : "left-1"}`} />
      </button>
      {label && <span className="text-sm">{label}</span>}
    </label>
  );
}

export function Segmented<T extends string>({ value, options, onChange, size = "md" }: { value: T; options: { value: T; label: ReactNode }[]; onChange: (v: T) => void; size?: "sm" | "md" }) {
  return (
    <div className="inline-flex rounded-xl border border-telemetry/20 bg-space-850 p-1">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={`rounded-lg font-semibold transition ${size === "sm" ? "px-2.5 py-1 text-xs" : "px-4 py-2 text-sm"} ${
            value === o.value ? "bg-telemetry text-space-950" : "text-slate-300 hover:bg-space-700"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; wide?: boolean }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-space-950/80 p-4 backdrop-blur-sm" onClick={onClose}>
      <div className={`panel max-h-[92vh] w-full overflow-auto p-6 ${wide ? "max-w-6xl" : "max-w-md"}`} onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-lg tracking-widest text-telemetry">{title}</h2>
          <button className="rounded-lg px-3 py-1 text-2xl text-slate-400 hover:bg-space-700" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold uppercase tracking-wider text-slate-400">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export const inputCls =
  "w-full rounded-lg border border-telemetry/20 bg-space-950/70 px-3 py-2 text-slate-100 outline-none focus:border-telemetry focus:ring-2 focus:ring-telemetry/30";

export function TraitBar({ value, max = 5, color = "#22d3ee" }: { value: number; max?: number; color?: string }) {
  return (
    <div className="flex gap-1">
      {Array.from({ length: max }, (_, i) => (
        <span key={i} className="h-2.5 w-6 rounded-sm" style={{ background: i < value ? color : "rgba(148,163,184,0.18)" }} />
      ))}
    </div>
  );
}

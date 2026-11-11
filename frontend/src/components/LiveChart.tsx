import { useEffect, useRef } from "react";
import { telemetry } from "../lib/telemetry";

const COLORS = { ax: "#f472b6", ay: "#a3e635", az: "#60a5fa", mag: "#22d3ee" };

/** Canvas strip chart of live telemetry (redrawn every animation frame). */
export function LiveChart({
  windowMs = 4000,
  rangeG = 16,
  simulated = false,
  emptyText = "Waiting for live sensor data…",
}: {
  windowMs?: number;
  rangeG?: number;
  simulated?: boolean;
  emptyText?: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const yMaxRef = useRef(3);

  useEffect(() => {
    let raf = 0;
    let lastDraw = 0;
    let lastKey = "";
    const draw = (now: number) => {
      raf = requestAnimationFrame(draw);
      const c = ref.current;
      if (!c) return;
      // Redraw at most ~30 fps, and only when new data arrived (or the
      // size / waiting state changed). Keeps the GPU/CPU load low on laptops.
      const latest = telemetry.latest();
      const stale = telemetry.msSinceLast() > 3000;
      const key = `${latest?.t ?? 0}|${c.clientWidth}x${c.clientHeight}|${stale}`;
      if (now - lastDraw < 33 || (key === lastKey && now - lastDraw < 1000)) return;
      lastDraw = now;
      lastKey = key;
      const dpr = window.devicePixelRatio || 1;
      const w = c.clientWidth;
      const h = c.clientHeight;
      if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
        c.width = Math.round(w * dpr);
        c.height = Math.round(h * dpr);
      }
      const ctx = c.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      const pts = telemetry.points();
      const last = pts[pts.length - 1];
      const tEnd = last ? last.t : 0;
      const tStart = tEnd - windowMs;
      let maxAbs = 2;
      let startIdx = pts.length;
      for (let i = pts.length - 1; i >= 0; i--) {
        if (pts[i].t < tStart) break;
        startIdx = i;
        const p = pts[i];
        for (const v of [p.ax, p.ay, p.az, p.mag]) if (v !== null && Math.abs(v) > maxAbs) maxAbs = Math.abs(v);
      }
      // Smoothly adapt the y scale to the data; never below ±2 g. |a| can
      // exceed the per-axis range (up to √3 × range), so allow for that.
      const target = Math.min(rangeG * Math.sqrt(3) * 1.1, Math.max(2.5, maxAbs * 1.15));
      yMaxRef.current += (target - yMaxRef.current) * (target > yMaxRef.current ? 0.5 : 0.03);
      const yMax = yMaxRef.current;
      const yMin = -Math.min(yMax, Math.max(2, yMax * 0.5));
      const padL = 44;
      const padB = 18;
      const X = (t: number) => padL + ((t - tStart) / windowMs) * (w - padL - 8);
      const Y = (v: number) => 8 + (1 - (v - yMin) / (yMax - yMin)) * (h - 8 - padB);

      // grid
      ctx.font = "11px JetBrains Mono, monospace";
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      const step = yMax > 12 ? 4 : yMax > 6 ? 2 : 1;
      for (let g = Math.ceil(yMin / step) * step; g <= yMax; g += step) {
        ctx.strokeStyle = g === 0 ? "rgba(148,163,184,0.35)" : "rgba(34,211,238,0.08)";
        ctx.beginPath();
        ctx.moveTo(padL, Y(g));
        ctx.lineTo(w - 8, Y(g));
        ctx.stroke();
        ctx.fillStyle = "rgba(148,163,184,0.8)";
        ctx.fillText(`${g}g`, padL - 6, Y(g));
      }
      if (!last || telemetry.msSinceLast() > 3000) {
        ctx.fillStyle = "rgba(148,163,184,0.7)";
        ctx.textAlign = "center";
        ctx.font = "16px Inter, sans-serif";
        ctx.fillText(emptyText, w / 2, h / 2);
        return;
      }

      const series: [keyof typeof COLORS, number][] = [
        ["ax", 1.2],
        ["ay", 1.2],
        ["az", 1.2],
        ["mag", 2.6],
      ];
      for (const [key, lw] of series) {
        ctx.strokeStyle = COLORS[key];
        ctx.lineWidth = lw;
        ctx.globalAlpha = key === "mag" ? 1 : 0.8;
        ctx.beginPath();
        let started = false;
        for (let i = startIdx; i < pts.length; i++) {
          const v = pts[i][key];
          if (v === null) {
            started = false;
            continue;
          }
          const x = X(pts[i].t);
          const y = Y(Math.max(yMin, Math.min(yMax, v)));
          if (!started) {
            ctx.moveTo(x, y);
            started = true;
          } else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
      if (simulated) {
        ctx.fillStyle = "rgba(192,132,252,0.9)";
        ctx.textAlign = "right";
        ctx.font = "bold 12px Orbitron, sans-serif";
        ctx.fillText("SIMULATED", w - 12, 18);
      }
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [windowMs, rangeG, simulated, emptyText]);

  return (
    <div className="relative h-full w-full">
      <canvas ref={ref} className="h-full w-full" />
      <div className="absolute bottom-0 right-2 flex gap-3 text-xs">
        {Object.entries({ "|a|": COLORS.mag, X: COLORS.ax, Y: COLORS.ay, Z: COLORS.az }).map(([k, col]) => (
          <span key={k} className="flex items-center gap-1 text-slate-300">
            <span className="h-1 w-4 rounded" style={{ background: col }} />
            {k}
          </span>
        ))}
      </div>
    </div>
  );
}

export function LiveMagnitude() {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    let raf = 0;
    let last = 0;
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      if (now - last < 80 || !ref.current) return;
      last = now;
      const p = telemetry.latest();
      ref.current.textContent = p && p.mag !== null && telemetry.msSinceLast() < 3000 ? p.mag.toFixed(2) : "—";
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);
  return <span ref={ref}>—</span>;
}

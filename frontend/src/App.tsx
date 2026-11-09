import { useEffect, useRef } from "react";
import { Shell } from "./components/Shell";
import { Briefing } from "./screens/Briefing";
import { Comparison } from "./screens/Comparison";
import { Designer } from "./screens/Designer";
import { LiveTest } from "./screens/LiveTest";
import { OperatorPanel } from "./screens/Operator";
import { Prediction } from "./screens/Prediction";
import { Results } from "./screens/Results";
import { useStore, type Screen } from "./state/store";

const NEXT: Partial<Record<Screen, Screen>> = { briefing: "design", design: "predict", predict: "test", results: "compare" };
const BACK: Partial<Record<Screen, Screen>> = { design: "briefing", predict: "design", test: "predict", results: "test", compare: "results" };

function useGlobalHotkeys() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const s = useStore.getState();
      const tag = (e.target as HTMLElement)?.tagName;
      const typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "o") {
        e.preventDefault();
        s.openOperator(!s.operatorOpen);
        return;
      }
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "h") {
        e.preventDefault();
        s.newMission();
        return;
      }
      if (s.operatorOpen) {
        if (e.key === "Escape") s.openOperator(false);
        return;
      }
      if (typing && s.screen !== "predict") return;
      if (e.key === "Enter") {
        const next = NEXT[s.screen];
        if (!next) return;
        if (s.screen === "design" && !s.configurationId) return;
        if (s.screen === "predict" && !s.prediction) return;
        e.preventDefault();
        s.go(next);
      } else if (e.key === "Escape" && s.screen !== "test") {
        const back = BACK[s.screen];
        if (back) s.go(back);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

/** Return to the Mission Briefing after a period of inactivity (kiosk). */
function useIdleReset() {
  const last = useRef(Date.now());
  useEffect(() => {
    const bump = () => (last.current = Date.now());
    const evs = ["pointerdown", "keydown", "wheel", "touchstart"];
    evs.forEach((e) => window.addEventListener(e, bump, { passive: true }));
    const t = window.setInterval(() => {
      const s = useStore.getState();
      const limit = (s.settings?.idle_reset_seconds ?? 120) * 1000;
      const busy = s.capture && ["baseline", "armed", "triggered", "analyzing"].includes(s.capture.state);
      if (!limit || busy || s.operatorOpen || s.screen === "briefing") return;
      if (Date.now() - last.current > limit) {
        s.newMission();
        last.current = Date.now();
      }
    }, 2000);
    return () => {
      evs.forEach((e) => window.removeEventListener(e, bump));
      window.clearInterval(t);
    };
  }, []);
}

export default function App() {
  const screen = useStore((s) => s.screen);
  const resetCounter = useStore((s) => s.resetCounter);
  useGlobalHotkeys();
  useIdleReset();

  return (
    <Shell>
      <div key={`${screen}-${resetCounter}`} className="h-full">
        {screen === "briefing" && <Briefing />}
        {screen === "design" && <Designer />}
        {screen === "predict" && <Prediction />}
        {screen === "test" && <LiveTest />}
        {screen === "results" && <Results />}
        {screen === "compare" && <Comparison />}
      </div>
      <OperatorPanel />
    </Shell>
  );
}

import { create } from "zustand";
import { api, getOperatorPin, setOperatorPin } from "../api/client";
import { StationSocket } from "../api/socket";
import type {
  CaptureSnapshot,
  Configuration,
  GradeBand,
  PredictionPayload,
  PublicSettings,
  SensorSnapshot,
  WsMessage,
} from "../api/types";
import { telemetry } from "../lib/telemetry";

export type Screen = "briefing" | "design" | "predict" | "test" | "results" | "compare";
export const SCREENS: { id: Screen; label: string }[] = [
  { id: "briefing", label: "Briefing" },
  { id: "design", label: "Design" },
  { id: "predict", label: "Predict" },
  { id: "test", label: "Test" },
  { id: "results", label: "Analyze" },
  { id: "compare", label: "Improve" },
];

interface Mission {
  screen: Screen;
  gradeBand: GradeBand;
  configurationId: number | null;
  prediction: PredictionPayload | null;
  dropHeight: number | null; // student-chosen height (simulation only)
  resultTestId: number | null;
}

interface Store extends Mission {
  wsConnected: boolean;
  sensor: SensorSnapshot | null;
  capture: CaptureSnapshot | null;
  settings: PublicSettings | null;
  configurations: Configuration[];
  operatorPinRequired: boolean;
  operatorUnlocked: boolean;
  operatorOpen: boolean;
  activeSessionId: number | null;
  dataVersion: number; // bumps when tests are saved/updated
  resetCounter: number;
  toast: { kind: "info" | "error" | "success"; text: string; id: number } | null;

  go: (s: Screen) => void;
  setGradeBand: (g: GradeBand) => void;
  selectConfiguration: (id: number) => void;
  setPrediction: (p: PredictionPayload | null) => void;
  setDropHeight: (h: number | null) => void;
  showResult: (testId: number) => void;
  newMission: () => void;
  refresh: () => Promise<void>;
  refreshConfigurations: () => Promise<void>;
  openOperator: (open: boolean) => void;
  unlockOperator: (pin: string) => Promise<boolean>;
  lockOperator: () => void;
  notify: (kind: "info" | "error" | "success", text: string) => void;
  setPreview: (on: boolean) => void;
}

const MISSION_KEY = "mm.mission";

function loadMission(): Partial<Mission> {
  try {
    return JSON.parse(sessionStorage.getItem(MISSION_KEY) ?? "{}");
  } catch {
    return {};
  }
}

function saveMission(m: Mission) {
  try {
    sessionStorage.setItem(MISSION_KEY, JSON.stringify(m));
  } catch {
    /* ignore */
  }
}

const initialMission: Mission = {
  screen: "briefing",
  gradeBand: "58",
  configurationId: null,
  prediction: null,
  dropHeight: null,
  resultTestId: null,
};

let socket: StationSocket | null = null;

export const useStore = create<Store>((set, get) => {
  const persist = () => {
    const s = get();
    saveMission({
      screen: s.screen,
      gradeBand: s.gradeBand,
      configurationId: s.configurationId,
      prediction: s.prediction,
      dropHeight: s.dropHeight,
      resultTestId: s.resultTestId,
    });
  };

  return {
    ...initialMission,
    ...loadMission(),
    wsConnected: false,
    sensor: null,
    capture: null,
    settings: null,
    configurations: [],
    operatorPinRequired: true,
    operatorUnlocked: false,
    operatorOpen: false,
    activeSessionId: null,
    dataVersion: 0,
    resetCounter: 0,
    toast: null,

    go: (screen) => {
      set({ screen });
      persist();
    },
    setGradeBand: (gradeBand) => {
      // The prediction format depends on the grade band.
      set({ gradeBand, prediction: null });
      persist();
    },
    selectConfiguration: (configurationId) => {
      set({ configurationId });
      persist();
    },
    setPrediction: (prediction) => {
      set({ prediction });
      persist();
    },
    setDropHeight: (dropHeight) => {
      set({ dropHeight });
      persist();
    },
    showResult: (resultTestId) => {
      set({ resultTestId, screen: "results" });
      persist();
    },
    newMission: () => {
      set({ ...initialMission, gradeBand: get().gradeBand, resetCounter: get().resetCounter + 1 });
      persist();
    },
    refresh: async () => {
      const st = await api.state();
      set({
        sensor: st.sensor,
        capture: st.capture,
        settings: st.settings,
        operatorPinRequired: st.operator_pin_required,
        activeSessionId: st.active_session_id,
      });
      if (!st.operator_pin_required && !get().operatorUnlocked) set({ operatorUnlocked: true });
    },
    refreshConfigurations: async () => {
      const configurations = await api.configurations();
      set({ configurations });
      const sel = get().configurationId;
      if (sel !== null && !configurations.find((c) => c.id === sel && c.enabled)) {
        set({ configurationId: null });
        persist();
      }
    },
    openOperator: (operatorOpen) => set({ operatorOpen }),
    unlockOperator: async (pin) => {
      setOperatorPin(pin);
      try {
        await api.verifyPin();
        set({ operatorUnlocked: true });
        return true;
      } catch {
        setOperatorPin("");
        set({ operatorUnlocked: false });
        return false;
      }
    },
    lockOperator: () => {
      setOperatorPin("");
      set({ operatorUnlocked: !get().operatorPinRequired, operatorOpen: false });
    },
    notify: (kind, text) => {
      const id = Date.now();
      set({ toast: { kind, text, id } });
      window.setTimeout(() => {
        if (get().toast?.id === id) set({ toast: null });
      }, kind === "error" ? 7000 : 3500);
    },
    setPreview: (on) => socket?.setPreview(on),
  };
});

function handleMessage(msg: WsMessage) {
  const s = useStore.getState();
  switch (msg.type) {
    case "hello":
      useStore.setState({ sensor: msg.sensor, capture: msg.capture });
      break;
    case "sensor":
      useStore.setState({ sensor: msg.sensor });
      break;
    case "capture":
      useStore.setState({ capture: msg.capture });
      break;
    case "telemetry":
      telemetry.push(msg.points, msg.data_origin);
      break;
    case "settings":
      useStore.setState({ settings: msg.settings });
      break;
    case "test_saved":
    case "test_updated":
      useStore.setState({ dataVersion: s.dataVersion + 1 });
      break;
    case "reset":
      s.newMission();
      useStore.setState({ operatorOpen: false });
      break;
    default:
      break;
  }
}

export async function bootstrap() {
  const store = useStore.getState();
  if (getOperatorPin()) {
    store.unlockOperator(getOperatorPin()).catch(() => undefined);
  }
  socket = new StationSocket(handleMessage, (connected) => {
    useStore.setState({ wsConnected: connected });
    if (connected) {
      store.refresh().catch(() => undefined);
      store.refreshConfigurations().catch(() => undefined);
    }
  });
  socket.start();
  try {
    await Promise.all([store.refresh(), store.refreshConfigurations()]);
  } catch {
    /* the socket reconnect will retry */
  }
  // Periodic refresh as a safety net if a WebSocket message was missed.
  window.setInterval(() => {
    useStore.getState().refresh().catch(() => undefined);
  }, 10000);
}

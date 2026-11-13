import type {
  AppState,
  CaptureSnapshot,
  Comparison,
  Configuration,
  DiagnosticsReport,
  LogEntry,
  PredictionPayload,
  ProbeResult,
  SensorMode,
  SensorSnapshot,
  Series,
  SessionInfo,
  SystemSettings,
  SystemView,
  TestDetail,
  TestSummary,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let operatorPin = "";
try {
  operatorPin = sessionStorage.getItem("mm.operatorPin") ?? "";
} catch {
  /* storage unavailable */
}

export function setOperatorPin(pin: string) {
  operatorPin = pin;
  try {
    if (pin) sessionStorage.setItem("mm.operatorPin", pin);
    else sessionStorage.removeItem("mm.operatorPin");
  } catch {
    /* ignore */
  }
}

export function getOperatorPin() {
  return operatorPin;
}

async function request<T>(method: string, path: string, body?: unknown, opts: { form?: FormData; timeoutMs?: number } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (operatorPin) headers["X-Operator-Pin"] = operatorPin;
  let payload: BodyInit | undefined;
  if (opts.form) payload = opts.form;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), opts.timeoutMs ?? 20000);
  let res: Response;
  try {
    res = await fetch(path, { method, headers, body: payload, signal: ctrl.signal });
  } catch (e) {
    throw new ApiError(0, (e as Error).name === "AbortError" ? "The station server did not respond in time." : "Cannot reach the station server.");
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg);
  }
  const ct = res.headers.get("content-type") ?? "";
  return (ct.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

const get = <T,>(p: string) => request<T>("GET", p);
const post = <T,>(p: string, b?: unknown) => request<T>("POST", p, b ?? {});

function qs(params: Record<string, string | number | boolean | null | undefined>) {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") s.set(k, String(v));
  const str = s.toString();
  return str ? `?${str}` : "";
}

export const api = {
  state: () => get<AppState>("/api/state"),
  configurations: () => get<Configuration[]>("/api/configurations"),
  updateConfiguration: (id: number, changes: Partial<Configuration>) => request<Configuration>("PATCH", `/api/configurations/${id}`, changes),
  restoreConfiguration: (id: number) => post<Configuration>(`/api/configurations/${id}/restore-defaults`),
  uploadPhoto: (id: number, file: File) => {
    const f = new FormData();
    f.append("file", file);
    return request<Configuration>("POST", `/api/configurations/${id}/photo`, undefined, { form: f });
  },
  deletePhoto: (id: number) => request<Configuration>("DELETE", `/api/configurations/${id}/photo`),

  arm: (b: { configuration_id: number; grade_band: string | null; prediction: PredictionPayload | null; drop_height_m?: number }) =>
    post<CaptureSnapshot>("/api/capture/arm", b),
  simulateDrop: () => post<CaptureSnapshot>("/api/capture/simulate-drop"),
  trigger: () => post<CaptureSnapshot>("/api/capture/trigger"),
  stop: () => post<CaptureSnapshot>("/api/capture/stop"),
  cancel: () => post<CaptureSnapshot>("/api/capture/cancel"),
  operatorReset: () => post<CaptureSnapshot>("/api/operator/reset"),
  /** Student "New mission": every screen back to the briefing (refused during a test). */
  missionReset: () => post<CaptureSnapshot>("/api/mission/reset"),
  verifyPin: () => post<{ ok: boolean }>("/api/operator/verify"),

  tests: (p: { session_id?: number | null; data_origin?: string | null; limit?: number } = {}) =>
    get<TestSummary[]>(`/api/tests${qs({ ...p })}`),
  test: (id: number) => get<TestDetail>(`/api/tests/${id}`),
  series: (id: number, maxPoints = 1600) => get<Series>(`/api/tests/${id}/series?max_points=${maxPoints}`),
  updateTest: (id: number, changes: Partial<TestSummary>) => request<TestDetail>("PATCH", `/api/tests/${id}`, changes),
  comparison: (p: { data_origin: string; session_id?: number | null; drop_height_m?: number | null; group_by?: string }) =>
    get<Comparison>(`/api/comparison${qs(p)}`),

  sessions: () => get<SessionInfo[]>("/api/sessions"),
  createSession: (name?: string) => post<SessionInfo>("/api/sessions", { name: name || null }),
  endSession: (id: number) => post<{ ok: boolean }>(`/api/sessions/${id}/end`),

  settings: () => get<Record<string, unknown>>("/api/settings"),
  updateSettings: (changes: Record<string, unknown>) => request<Record<string, unknown>>("PATCH", "/api/settings", changes),
  restoreSettings: () => post<Record<string, unknown>>("/api/settings/restore-defaults"),

  sensor: () => get<SensorSnapshot>("/api/sensor"),
  setMode: (mode: SensorMode) => post<SensorSnapshot>("/api/sensor/mode", { mode }),
  configureEvb: (b: { host?: string; port?: number; timeout_s?: number }) => request<SensorSnapshot>("PUT", "/api/sensor/evb", b),
  connect: () => post<SensorSnapshot>("/api/sensor/connect"),
  disconnect: () => post<SensorSnapshot>("/api/sensor/disconnect"),
  reloadProfile: () => post<Record<string, unknown>>("/api/sensor/reload-profile"),
  diagnostics: () => request<DiagnosticsReport>("POST", "/api/sensor/diagnostics", {}, { timeoutMs: 60000 }),
  probe: (path: string) => request<ProbeResult>("POST", "/api/sensor/probe", { path }, { timeoutMs: 60000 }),
  uploadReplay: (file: File, opts: { data_origin: string; loop: boolean; time_unit?: string; accel_unit?: string }) => {
    const f = new FormData();
    f.append("file", file);
    f.append("data_origin", opts.data_origin);
    f.append("loop", String(opts.loop));
    if (opts.time_unit) f.append("time_unit", opts.time_unit);
    if (opts.accel_unit) f.append("accel_unit", opts.accel_unit);
    return request<{ rows: number; warnings: string[] }>("POST", "/api/sensor/replay", undefined, { form: f });
  },
  importCsv: (file: File, opts: { configuration_id?: number; drop_height_m?: number; data_origin: string; time_unit?: string; accel_unit?: string; notes?: string }) => {
    const f = new FormData();
    f.append("file", file);
    for (const [k, v] of Object.entries(opts)) if (v !== undefined && v !== "") f.append(k, String(v));
    return request<TestDetail>("POST", "/api/tests/import-csv", undefined, { form: f, timeoutMs: 60000 });
  },
  logs: (level?: string) => get<LogEntry[]>(`/api/logs${qs({ level })}`),
  system: () => get<SystemView>("/api/system"),
  updateSystem: (changes: Partial<SystemSettings>) => request<SystemView>("PUT", "/api/system", changes, { timeoutMs: 30000 }),
  changePin: (new_pin: string) => post<{ ok: boolean }>("/api/system/pin", { new_pin }),
  resetPin: () => request<{ ok: boolean }>("DELETE", "/api/system/pin"),
  exportUrl: (path: string, params: Record<string, string | number | null | undefined> = {}) =>
    `${path}${qs({ ...params, pin: operatorPin || undefined })}`,
};

// Shapes returned by the FastAPI backend (backend/app/api/routes.py).

export type DataOrigin = "physical" | "simulated" | "unverified";
export type SensorMode = "simulation" | "evb_lite" | "csv_replay";
export type GradeBand = "k4" | "58" | "912";
export type CaptureStateName =
  | "idle"
  | "baseline"
  | "armed"
  | "triggered"
  | "analyzing"
  | "complete"
  | "error";

export interface ProfileSummary {
  verified: boolean;
  verified_by: string;
  verified_on: string;
  source_of_truth: string;
  device_model: string;
  firmware_version: string;
  status_path: string | null;
  samples_path: string | null;
  samples_format: string;
  poll_interval_ms: number;
  timestamp_unit: string;
  accel_unit: string;
  axis_map: Record<string, string>;
  has_start_request: boolean;
  has_stop_request: boolean;
  streaming_ready: boolean;
  loaded_from: string | null;
  problems: string[];
}

export interface SensorSnapshot {
  mode: SensorMode;
  adapter: string;
  source: string;
  data_origin: DataOrigin;
  simulated: boolean;
  state: "disconnected" | "connecting" | "connected" | "capturing" | "error" | "not_configured";
  connected: boolean;
  streaming: boolean;
  manual_offline: boolean;
  model: string | null;
  firmware_version: string | null;
  sensor_id: string | null;
  accel_range_g: number;
  nominal_rate_hz: number | null;
  observed_rate_hz: number | null;
  last_success_at: string | null;
  seconds_since_success: number | null;
  last_error: string | null;
  last_error_at: string | null;
  stream_error: string | null;
  consecutive_failures: number;
  next_retry_in_s: number | null;
  samples_received: number;
  battery_percent: number | null;
  detail: Record<string, unknown>;
  streaming_available: boolean;
  host?: string;
  port?: number;
  profile?: ProfileSummary;
  last_http?: Record<string, unknown>;
  replay?: { file: string | null; rows: number; data_origin: DataOrigin; finished: boolean };
}

export interface PredictionPayload {
  kind: "category" | "range" | "number";
  label?: string | null;
  value_g?: number | null;
  low_g?: number | null;
  high_g?: number | null;
}

export interface CaptureSnapshot {
  state: CaptureStateName;
  message: string;
  error: string | null;
  test_id: number | null;
  armed_seconds: number | null;
  freefall_seen: boolean;
  trigger_reason: string | null;
  live_peak_g: number | null;
  baseline: { magnitude_g: number; noise_std_g: number; stationary: boolean } | null;
  mission: {
    configuration_id: number;
    configuration_code: string;
    configuration_name: string;
    drop_height_m: number;
    gravity_m_s2: number;
    grade_band: GradeBand | null;
    prediction: PredictionPayload | null;
    data_origin: DataOrigin;
    source: string;
  } | null;
}

export interface Criteria {
  success_max_peak_g: number;
  mass_budget_kg: number;
  require_payload_retained: boolean;
  require_stable_landing: boolean;
  gentle_max_g: number;
  medium_max_g: number;
}

export interface PublicSettings {
  drop_height_m: number;
  drop_height_options_m: number[];
  allow_student_height_change: boolean;
  idle_reset_seconds: number;
  criteria: Criteria;
  prediction_ranges_g: [number, number][];
  sim_gravity: "earth" | "mars";
  pre_trigger_s: number;
  post_trigger_s: number;
}

export interface AppState {
  app: string;
  sensor: SensorSnapshot;
  capture: CaptureSnapshot;
  settings: PublicSettings;
  active_session_id: number | null;
  operator_pin_required: boolean;
  counts: Partial<Record<DataOrigin, number>>;
}

export interface Geometry {
  leg_style: "strut" | "strut_spring";
  foot_shape: "pad" | "block" | "dome";
  foot_material: "hard" | "foam" | "rubber";
  foot_color: string;
  foot_size: number;
  spring: boolean;
}

export interface Configuration {
  id: number;
  code: string;
  name: string;
  material: string;
  description: string;
  mass_kg: number;
  display_color: string;
  photo_url: string | null;
  enabled: boolean;
  sort_order: number;
  parameters_json: {
    geometry?: Geometry;
    sim?: Record<string, number | null>;
    traits?: Record<string, number>;
  };
  updated_at: string | null;
}

export interface QualityFlag {
  code: string;
  severity: "error" | "warning" | "info";
  message: string;
}

export interface TestSummary {
  id: number;
  session_id: number | null;
  configuration_id: number | null;
  configuration_code: string | null;
  configuration_name: string | null;
  source: string;
  data_origin: DataOrigin;
  timestamp: string;
  drop_height_m: number | null;
  gravity_m_s2: number;
  mass_kg: number | null;
  grade_band: GradeBand | null;
  prediction_kind: string | null;
  prediction_label: string | null;
  predicted_peak_g: number | null;
  predicted_low_g: number | null;
  predicted_high_g: number | null;
  measured_peak_g: number | null;
  observed_max_g: number | null;
  gravity_comp_peak_g: number | null;
  outcome: "success" | "needs_improvement" | "invalid";
  saturated: boolean;
  valid: boolean;
  excluded: boolean;
  exclude_reason: string | null;
  quality_flags: QualityFlag[];
  sample_count: number;
  sample_rate_hz: number | null;
  duration_s: number | null;
  landing_stable: boolean | null;
  payload_retained: boolean | null;
  notes: string | null;
}

export interface TestDetail extends TestSummary {
  raw_payload_count?: number;
  analysis: {
    sampling?: {
      observed_rate_hz: number | null;
      nominal_rate_hz: number | null;
      completeness: number | null;
      gap_count: number;
      max_gap_ms: number | null;
      duplicate_timestamps: number;
      invalid_sample_count: number;
      sample_count: number;
      duration_s: number;
    };
    saturation?: { saturated: boolean; range_g: number; per_axis_counts: Record<string, number> };
    detection?: {
      impact_detected: boolean;
      peak_g: number | null;
      per_axis_peak_g: Record<string, number> | null;
      gravity_comp_peak_g: number | null;
      pulse_width_ms: number | null;
      samples_in_pulse: number | null;
      time_to_peak_ms: number | null;
      delta_v_m_s: number | null;
      freefall: { duration_ms: number; estimated_drop_height_m: number } | null;
      secondary: { kind: string; peak_g: number }[];
      baseline: { magnitude_g: number; noise_std_g: number; stationary: boolean; source: string };
      messages: string[];
    };
    physics?: {
      gravity_m_s2: number;
      gravity_label: string;
      impact_speed_m_s?: number;
      free_fall_time_s?: number;
      potential_energy_j?: number;
      estimated_support_force_n?: number;
      estimated_net_force_n?: number;
      estimated_delta_v_m_s?: number;
      weight_n?: number;
      contact_force_note: string;
      assumptions: string[];
    };
    outcome_reasons?: string[];
    prediction_comparison?: {
      kind: string;
      error_g?: number;
      percent_error?: number | null;
      inside_range?: boolean;
      close: boolean;
      direction: string;
    } | null;
    criteria?: Criteria;
    simulation?: { seed: number | null; true_peak_g: number };
  };
}

export interface Series {
  n: number;
  points: number;
  decimated: boolean;
  decimation: string;
  time_zero: string;
  t_ms: number[];
  ax: (number | null)[];
  ay: (number | null)[];
  az: (number | null)[];
  mag: (number | null)[];
  mag_filtered: (number | null)[];
  filter_method: string;
  markers: {
    peak_ms?: number | null;
    impact_start_ms?: number | null;
    impact_end_ms?: number | null;
    freefall_start_ms?: number | null;
    freefall_end_ms?: number | null;
    rebounds_ms?: (number | null)[];
    trigger_ms?: number | null;
  };
  range_g: number | null;
}

export interface ComparisonGroup {
  configuration_code: string;
  configuration_name: string | null;
  group: string;
  color: string;
  total: number;
  valid: number;
  saturated: number;
  invalid: number;
  excluded: number;
  successes: number;
  mean_peak_g: number | null;
  min_peak_g: number | null;
  max_peak_g: number | null;
  std_peak_g: number | null;
  rank?: number;
}

export interface Comparison {
  data_origin: DataOrigin;
  group_by: string;
  drop_height_m: number | null;
  heights_available_m: number[];
  groups: ComparisonGroup[];
  ranking: { rank: number; configuration_code: string; group: string; mean_peak_g: number; valid: number }[];
  points: { id: number; timestamp: string; configuration_code: string; measured_peak_g: number; drop_height_m: number }[];
  note: string;
}

export interface SessionInfo {
  id: number;
  name: string;
  started_at: string;
  ended_at: string | null;
  test_count: number;
  active: boolean;
}

export interface LogEntry {
  time: string;
  level: string;
  logger: string;
  message: string;
}

export interface DiagnosticsReport {
  host: string;
  port: number;
  ok: boolean;
  steps: { name: string; ok: boolean; detail: string; ms?: number }[];
  hints: string[];
  profile?: ProfileSummary;
}

export interface ProbeResult {
  url: string;
  status?: number;
  elapsed_ms?: number;
  headers?: Record<string, string>;
  content_type?: string;
  length?: number;
  truncated?: boolean;
  body_text?: string;
  body_base64?: string;
  html_title?: string;
  error?: string;
  summary?: string;
  saved_to?: string;
}

export type WsMessage =
  | { type: "hello"; sensor: SensorSnapshot; capture: CaptureSnapshot; server_time: number }
  | { type: "sensor"; sensor: SensorSnapshot }
  | { type: "capture"; capture: CaptureSnapshot }
  | { type: "telemetry"; source: string; data_origin: DataOrigin; points: [number, number | null, number | null, number | null, number | null][] }
  | { type: "test_saved"; test_id: number }
  | { type: "test_updated"; test_id: number }
  | { type: "settings"; settings: PublicSettings }
  | { type: "reset"; at: number }
  | { type: "pong"; server_time: number };

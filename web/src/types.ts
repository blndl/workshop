// Shapes returned by the API (services/api). Keep in sync with alarm-core's README.

export type AlarmState = "disarmed" | "arming" | "armed" | "entry_delay" | "triggered";

export type Role = "entry" | "instant" | "tamper" | "safety" | "telemetry";

/** One sensor, as described in config/modules.yaml. */
export interface SensorInfo {
  kind: string;
  role: Role;
  binary: boolean;
  label: string;
  unit?: string;
  alarm_above?: number;
  alarm_below?: number;
  normal?: number;
}

export interface NodeState {
  type: string;
  name: string;
  online: boolean;
  sensors: Record<string, string>; // last reported values: "0"/"1", or a number as text
  active: Record<string, boolean>; // in its alarm condition
  info: Record<string, SensorInfo>;
  rssi: number | null;
  uptime: number | null;
  seen_ago: number | null;
  security: Partial<Record<"auth_fail" | "replay", number>>;
}

export interface StateSnapshot {
  ts: number;
  state: AlarmState;
  reason: string;
  node: string | null;
  siren: boolean;
  deadline_in: number | null;
  safety: { node: string; sensor: string; kind: string; value: string; unit: string; since_s: number }[];
  safety_silenced: boolean;
  nodes: Record<string, NodeState>;
  log?: { seq: number; head: string };
}

export interface AlarmEvent {
  ts: number;
  type: string;
  seq?: number;
  [field: string]: unknown;
}

export interface Health {
  mqtt_connected: boolean;
  state_received: boolean;
  state_age_s: number | null;
}

export interface ControlResult {
  result: "ok" | "no_change" | "bad_code" | "locked" | "lockout" | "arm_refused";
  state?: AlarmState;
  prev?: AlarmState;
  delay?: number;
  detail?: string | string[];
  silenced?: string[];
}

export interface SimNodeStatus {
  node: string;
  state: "offline" | "handshaking" | "session" | "silent";
  session: string | null;
  sensors: Record<string, string>;
  outputs: { buzzer: "0" | "1"; led: "off" | "armed" | "alarm" };
  silent_for: number;
  attacks: string[];
  last_command: { cmd: string; ok: boolean; error?: string } | null;
  received_at: number;
  age_s: number; // seconds since the API last heard from it
}

export interface SimInfo {
  enabled: boolean;
  nodes: Record<string, SimNodeStatus>;
}

export type SimCommand =
  | { cmd: "set"; sensor: string; value: number }
  | { cmd: "jam"; seconds: number }
  | { cmd: "reboot"; seconds?: number }
  | { cmd: "attack"; name: string; args?: Record<string, number | string> };

export interface DetectionBox {
  label: string;
  confidence: number;
  x: number; // 0-1, from the left
  y: number; // 0-1, from the top
  w: number;
  h: number;
}

export interface Snapshot {
  path: string;
  ts: number;
  reason: string;
  seq?: number;
  url: string;
  verified: boolean | null; // file matches the sha256 in the tamper-evident log
  detection: {
    person: boolean;
    confidence: number;
    objects: Record<string, number>;
    boxes: DetectionBox[];
    latency_ms: number;
  } | null;
}

export interface CameraInfo {
  camera: { open: boolean; why: string; source: string; live: boolean; error: boolean; frames: number; snapshots: number } | null;
  streaming: boolean;
  detector: { ready: boolean; model: string; error: string | null; processed: number; persons: number; last_latency_ms: number | null } | null;
  live_view_s: number;
  verifying: { node: string; sensor: string } | null;
  stats: {
    photos: number;
    analysed: number;
    with_person: number;
    motion_confirmed: number;
    motion_dismissed: number;
    verify_timeouts: number;
    median_latency_ms: number | null;
  };
}

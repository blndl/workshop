// Shapes returned by the API (services/api). Keep in sync with alarm-core's README.

export type AlarmState = "disarmed" | "arming" | "armed" | "entry_delay" | "triggered";

export interface NodeState {
  online: boolean;
  sensors: Partial<Record<"door" | "pir" | "lid", "0" | "1">>;
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
}

export interface SimNodeStatus {
  node: string;
  state: "offline" | "handshaking" | "session" | "silent";
  session: string | null;
  sensors: Record<"door" | "pir" | "lid", "0" | "1">;
  outputs: { buzzer: "0" | "1"; led: "off" | "armed" | "alarm" };
  silent_for: number;
  attacks: string[];
  last_command: { cmd: string; ok: boolean; error?: string } | null;
  received_at: number;
}

export interface SimInfo {
  enabled: boolean;
  nodes: Record<string, SimNodeStatus>;
}

export type SimCommand =
  | { cmd: "set"; sensor: "door" | "pir" | "lid"; value: 0 | 1 }
  | { cmd: "jam"; seconds: number }
  | { cmd: "reboot"; seconds?: number }
  | { cmd: "attack"; name: string; args?: Record<string, number | string> };

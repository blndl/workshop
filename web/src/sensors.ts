import type { SensorInfo } from "./types";

// Words for on/off sensors, by kind: [inactive, active].
const STATES: Record<string, [string, string]> = {
  contact: ["closed", "open"],
  motion: ["none", "detected"],
  tamper: ["closed", "open"],
  smoke: ["clear", "SMOKE"],
  water: ["dry", "LEAK"],
  vibration: ["still", "shaking"],
  glass_break: ["intact", "BROKEN"],
  button: ["released", "pressed"],
};

export const sensorLabel = (name: string, info?: SensorInfo) => info?.label || name;

/** "open", "21.4 °C"… */
export function sensorText(value: string | undefined, info?: SensorInfo): string {
  if (value === undefined) return "-";
  if (!info || info.binary) return (STATES[info?.kind ?? ""] ?? ["off", "on"])[value === "1" ? 1 : 0];
  return `${value}${info.unit ? ` ${info.unit}` : ""}`;
}

/** "alarm ≥ 400 ppm", or "" */
export function thresholdText(info?: SensorInfo): string {
  if (!info || info.binary) return "";
  const unit = info.unit ? ` ${info.unit}` : "";
  if (info.alarm_above !== undefined) return `alarm ≥ ${info.alarm_above}${unit}`;
  if (info.alarm_below !== undefined) return `alarm ≤ ${info.alarm_below}${unit}`;
  return "";
}

/** Button text to flip an on/off sensor in the simulator. */
export function toggleText(active: boolean, label: string, kind: string): string {
  if (kind === "contact" || kind === "tamper") return `${active ? "Close" : "Open"} ${label.toLowerCase()}`;
  return `${active ? "Stop" : "Trigger"} ${label.toLowerCase()}`;
}

/** A reading that crosses the threshold, for the simulator's "Alarm" button. */
export function alarmValue(info: SensorInfo): number | undefined {
  if (info.alarm_above !== undefined) return Math.round(info.alarm_above * 1.5 * 10) / 10;
  if (info.alarm_below !== undefined) return Math.round((info.alarm_below - Math.max(1, Math.abs(info.alarm_below) * 0.5)) * 10) / 10;
  return undefined;
}

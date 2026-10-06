import type { AlarmEvent } from "./types";

export type Severity = "ok" | "info" | "warn" | "danger";

export const clock = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour12: false });

export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return "-";
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${s}s`;
}

export const STATE_LABEL: Record<string, string> = {
  disarmed: "Disarmed",
  arming: "Arming",
  armed: "Armed",
  entry_delay: "Entry delay",
  triggered: "ALARM",
};

const SENSOR_WORDS: Record<string, [string, string]> = {
  door: ["closed", "opened"],
  pir: ["no motion", "motion"],
  lid: ["closed", "opened"],
};

/** One line of text and a severity for the timeline. */
export function describe(e: AlarmEvent): { text: string; severity: Severity } {
  const node = e.node ? ` (${e.node})` : "";
  switch (e.type) {
    case "state": {
      const sev: Severity = e.state === "triggered" ? "danger" : e.state === "entry_delay" ? "warn" : "info";
      return { text: `${STATE_LABEL[e.prev as string] ?? e.prev} → ${STATE_LABEL[e.state as string] ?? e.state}: ${e.reason}`, severity: sev };
    }
    case "sensor": {
      const words = SENSOR_WORDS[e.sensor as string] ?? ["0", "1"];
      return { text: `${e.sensor} ${words[e.value === "1" ? 1 : 0]}${node}`, severity: "info" };
    }
    case "security":
      return { text: `Rejected ${e.kind === "replay" ? "replayed" : "forged"} message${node}`, severity: "danger" };
    case "link_lost":
      return { text: `Link lost${node}`, severity: "danger" };
    case "node_online":
      return { text: `Node online${node}`, severity: "ok" };
    case "tamper":
      return { text: `Enclosure opened while disarmed${node}`, severity: "warn" };
    case "bad_code":
      return { text: `Wrong code (${e.action}, ${e.source})`, severity: "warn" };
    case "code_lockout":
      return { text: `Code lockout started (${e.source})`, severity: "danger" };
    case "code_locked":
      return { text: `Code refused during lockout (${e.source})`, severity: "warn" };
    case "arm_refused":
      return { text: `Arming refused: ${(e.problems as string[] | undefined)?.join(", ")}`, severity: "warn" };
    case "snapshot":
      return { text: `Photo taken: ${e.reason}`, severity: "info" };
    case "camera_error":
      return { text: `Camera error: ${e.error}`, severity: "danger" };
    case "log_tampered":
      return { text: `Event log tampered (${e.count} problems)`, severity: "danger" };
    case "siren_timeout":
      return { text: `Siren stopped after ${e.seconds}s`, severity: "info" };
    default:
      return { text: e.type, severity: "info" };
  }
}

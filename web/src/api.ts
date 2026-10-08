import type { AlarmEvent, CameraInfo, ControlResult, Health, SimCommand, SimInfo, Snapshot, StateSnapshot } from "./types";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<{ status: number; body: T }> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const json = await r.json().catch(() => ({}));
  if (r.status === 422) throw new Error("invalid input");
  if (r.status >= 500) throw new Error((json as { detail?: string }).detail ?? `HTTP ${r.status}`);
  return { status: r.status, body: json as T };
}

export const api = {
  health: () => get<Health>("/api/health"),
  state: () => get<StateSnapshot>("/api/state"),
  events: (limit = 100) => get<AlarmEvent[]>(`/api/events?limit=${limit}`),
  sim: () => get<SimInfo>("/api/sim"),
  info: () => get<{ grafana_url: string | null }>("/api/info"),
  camera: () => get<CameraInfo>("/api/camera"),
  snapshots: (limit = 60) => get<Snapshot[]>(`/api/camera/snapshots?limit=${limit}`),
  liveView: (on: boolean) => post<{ on: boolean; seconds: number | null }>("/api/camera/live", { on }),
  arm: (code: string) => post<ControlResult>("/api/arm", { code }),
  disarm: (code: string) => post<ControlResult>("/api/disarm", { code }),
  simCommand: (node: string, command: SimCommand) => post<{ sent: boolean }>(`/api/sim/${node}/command`, command),
};

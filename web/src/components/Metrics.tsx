import type { AlarmEvent } from "../types";

/** Counts over the events the API keeps in memory (up to 500). */
export function Metrics({ events }: { events: AlarmEvent[] }) {
  const count = (pred: (e: AlarmEvent) => boolean) => events.filter(pred).length;
  const tiles = [
    { label: "Alarms", value: count((e) => e.type === "state" && e.state === "triggered"), bad: true },
    { label: "Rejected messages", value: count((e) => e.type === "security"), bad: true },
    { label: "Link losses", value: count((e) => e.type === "link_lost"), bad: true },
    { label: "Wrong codes", value: count((e) => e.type === "bad_code" || e.type === "code_lockout"), bad: true },
    { label: "Sensor events", value: count((e) => e.type === "sensor"), bad: false },
    { label: "Photos", value: count((e) => e.type === "snapshot"), bad: false },
  ];
  const since = events.length ? new Date(events[events.length - 1].ts * 1000).toLocaleTimeString([], { hour12: false }) : null;
  return (
    <section className="card">
      <h2>Metrics</h2>
      <div className="tiles">
        {tiles.map((t) => (
          <div key={t.label} className={t.bad && t.value ? "tile bad" : "tile"}>
            <strong>{t.value}</strong>
            <span>{t.label}</span>
          </div>
        ))}
      </div>
      <p className="muted small">{since ? `Since ${since} (last ${events.length} events)` : "No events yet"}</p>
    </section>
  );
}

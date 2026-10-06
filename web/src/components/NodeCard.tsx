import { duration } from "../format";
import type { NodeState } from "../types";
import { Sparkline } from "./Sparkline";

const SENSORS: { key: "door" | "pir" | "lid"; label: string; on: string; off: string }[] = [
  { key: "door", label: "Door", on: "open", off: "closed" },
  { key: "pir", label: "Motion", on: "detected", off: "none" },
  { key: "lid", label: "Lid", on: "open", off: "closed" },
];

export function NodeCard({ name, node, rssiHistory }: { name: string; node: NodeState; rssiHistory: number[] }) {
  const security = (node.security.auth_fail ?? 0) + (node.security.replay ?? 0);
  return (
    <section className="card node">
      <header>
        <h3>{name}</h3>
        <span className={node.online ? "pill ok" : "pill bad"}>{node.online ? "online" : "offline"}</span>
      </header>
      <div className="sensors">
        {SENSORS.map((s) => {
          const on = node.sensors[s.key] === "1";
          return (
            <div key={s.key} className={on ? "sensor on" : "sensor"}>
              <span>{s.label}</span>
              <strong>{on ? s.on : s.off}</strong>
            </div>
          );
        })}
      </div>
      <div className="node-metrics">
        <div>
          <span className="muted">Wi-Fi signal</span>
          <strong>{node.rssi != null ? `${node.rssi} dBm` : "-"}</strong>
          <Sparkline values={rssiHistory} min={-90} max={-40} />
        </div>
        <dl>
          <dt>Uptime</dt>
          <dd>{duration(node.uptime)}</dd>
          <dt>Last heard</dt>
          <dd>{node.seen_ago != null ? `${node.seen_ago.toFixed(1)} s ago` : "-"}</dd>
          <dt>Rejected messages</dt>
          <dd className={security ? "bad-text" : ""}>{security}</dd>
        </dl>
      </div>
    </section>
  );
}

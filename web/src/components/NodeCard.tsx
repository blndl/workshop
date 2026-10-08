import { duration } from "../format";
import { sensorLabel, sensorText, thresholdText } from "../sensors";
import type { NodeState } from "../types";
import { Sparkline } from "./Sparkline";

/** One module, drawn from its description: on/off tiles, numeric readings with a chart. */
export function NodeCard({ id, node, history }: { id: string; node: NodeState; history: Record<string, number[]> }) {
  const security = (node.security.auth_fail ?? 0) + (node.security.replay ?? 0);
  const names = Object.keys(node.info);
  const binary = names.filter((n) => node.info[n].binary);
  const numeric = names.filter((n) => !node.info[n].binary);
  return (
    <section className="card node">
      <header>
        <h3>
          {node.name} <span className="muted small">{id} · {node.type}</span>
        </h3>
        <span className={node.online ? "pill ok" : "pill bad"}>{node.online ? "online" : "offline"}</span>
      </header>

      {binary.length > 0 && (
        <div className="sensors">
          {binary.map((n) => (
            <div key={n} className={node.active[n] ? `sensor on role-${node.info[n].role}` : "sensor"}>
              <span>{sensorLabel(n, node.info[n])}</span>
              <strong>{sensorText(node.sensors[n], node.info[n])}</strong>
            </div>
          ))}
        </div>
      )}

      {numeric.length > 0 && (
        <div className="readings">
          {numeric.map((n) => {
            const info = node.info[n];
            return (
              <div key={n} className={node.active[n] ? "reading alarm" : "reading"}>
                <div>
                  <span className="muted">{sensorLabel(n, info)}</span>
                  <strong>{sensorText(node.sensors[n], info)}</strong>
                  <span className="muted small">{thresholdText(info) || "chart only"}</span>
                </div>
                <Sparkline values={history[n] ?? []} min={rangeMin(info, history[n])} max={rangeMax(info, history[n])} width={120} />
              </div>
            );
          })}
        </div>
      )}

      <div className="node-metrics">
        <div>
          <span className="muted">Wi-Fi signal</span>
          <strong>{node.rssi != null ? `${node.rssi} dBm` : "-"}</strong>
          <Sparkline values={history.__rssi ?? []} min={-90} max={-40} />
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

// Chart range: include the threshold, so you see how close a reading is to it.
function rangeMin(info: NodeState["info"][string], values: number[] = []) {
  return Math.min(...values, info.alarm_below ?? Infinity, info.normal ?? Infinity) * 0.9 || 0;
}
function rangeMax(info: NodeState["info"][string], values: number[] = []) {
  return Math.max(...values, info.alarm_above ?? -Infinity, (info.normal ?? 0) * 1.2, 1) * 1.05;
}

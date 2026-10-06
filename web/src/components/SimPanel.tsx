import { useState } from "react";
import { api } from "../api";
import type { SimCommand, SimNodeStatus } from "../types";

/** Dev only: drives the simulated ESPs (the API must run with --sim). */
export function SimPanel({ nodes }: { nodes: Record<string, SimNodeStatus> }) {
  const names = Object.keys(nodes).sort();
  return (
    <section className="card sim">
      <h2>
        Simulator <span className="pill warn">dev only</span>
      </h2>
      {names.length === 0 && (
        <p className="muted">No simulated node yet. Start one: <code>.venv/bin/python -m alarm_sim node --headless</code></p>
      )}
      <div className="sim-nodes">
        {names.map((n) => (
          <SimNode key={n} status={nodes[n]} />
        ))}
      </div>
    </section>
  );
}

function SimNode({ status }: { status: SimNodeStatus }) {
  const [attack, setAttack] = useState(status.attacks[0] ?? "");
  const [error, setError] = useState<string | null>(null);
  const stale = Date.now() / 1000 - status.received_at > 5;

  const send = async (command: SimCommand) => {
    setError(null);
    try {
      await api.simCommand(status.node, command);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  const toggle = (sensor: "door" | "pir" | "lid") =>
    send({ cmd: "set", sensor, value: status.sensors[sensor] === "1" ? 0 : 1 });

  const last = status.last_command;
  return (
    <div className={stale ? "sim-node stale" : "sim-node"}>
      <header>
        <h3>{status.node}</h3>
        <span className={`pill ${status.state === "session" ? "ok" : "bad"}`}>
          {stale ? "not responding" : status.state === "silent" ? `silent ${status.silent_for}s` : status.state}
        </span>
      </header>

      <div className="device">
        <div className={`led led-${status.outputs.led}`} title={`LED: ${status.outputs.led}`} />
        <span>LED {status.outputs.led}</span>
        <div className={status.outputs.buzzer === "1" ? "buzzer on" : "buzzer"}>
          {status.outputs.buzzer === "1" ? "BUZZER ON" : "buzzer off"}
        </div>
      </div>

      <div className="sim-row">
        <button onClick={() => toggle("door")}>{status.sensors.door === "1" ? "Close door" : "Open door"}</button>
        <button onClick={() => toggle("pir")}>{status.sensors.pir === "1" ? "Stop motion" : "Motion"}</button>
        <button onClick={() => toggle("lid")}>{status.sensors.lid === "1" ? "Close lid" : "Open lid"}</button>
      </div>
      <div className="sim-row">
        <button className="secondary" onClick={() => send({ cmd: "jam", seconds: 6 })}>Jam Wi-Fi 6 s</button>
        <button className="secondary" onClick={() => send({ cmd: "reboot", seconds: 2 })}>Reboot</button>
      </div>
      {status.attacks.length > 0 && (
        <div className="sim-row">
          <select value={attack} onChange={(e) => setAttack(e.target.value)} aria-label="attack">
            {status.attacks.map((a) => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>
          <button className="danger" onClick={() => send({ cmd: "attack", name: attack })}>Run attack</button>
        </div>
      )}
      {error && <p className="msg bad">{error}</p>}
      {last && (
        <p className={last.ok ? "msg ok small" : "msg bad small"}>
          {last.ok ? "✓ " : "✗ "}
          {describeCommand(last.cmd)}
          {last.error ? `: ${last.error}` : ""}
        </p>
      )}
    </div>
  );
}

const SENSOR_ACTION: Record<string, [string, string]> = {
  door: ["Close door", "Open door"],
  pir: ["Motion stopped", "Motion"],
  lid: ["Close lid", "Open lid"],
};

/** Turn the echoed JSON command into words, e.g. "Open door" or "Attack: spoof". */
function describeCommand(raw: string): string {
  try {
    const c = JSON.parse(raw) as Record<string, unknown>;
    if (c.cmd === "set") return SENSOR_ACTION[c.sensor as string]?.[Number(c.value)] ?? raw;
    if (c.cmd === "jam") return `Jam Wi-Fi ${c.seconds} s`;
    if (c.cmd === "reboot") return "Reboot";
    if (c.cmd === "attack") return `Attack: ${c.name}`;
  } catch {
    // not JSON: show as is
  }
  return raw;
}

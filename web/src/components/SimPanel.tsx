import { useState } from "react";
import { api } from "../api";
import { alarmValue, sensorLabel, toggleText } from "../sensors";
import type { NodeState, SimCommand, SimNodeStatus } from "../types";

/** Dev only: drives the simulated modules (the API must run with --sim). */
export function SimPanel({ nodes, described }: { nodes: Record<string, SimNodeStatus>; described: Record<string, NodeState> }) {
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
          <SimNode key={n} status={nodes[n]} module={described[n]} />
        ))}
      </div>
    </section>
  );
}

function SimNode({ status, module }: { status: SimNodeStatus; module?: NodeState }) {
  const [attack, setAttack] = useState(status.attacks[0] ?? "");
  const [error, setError] = useState<string | null>(null);
  const stale = status.age_s > 5;

  const send = async (command: SimCommand) => {
    setError(null);
    try {
      await api.simCommand(status.node, command);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  const toggle = (sensor: string) => send({ cmd: "set", sensor, value: status.sensors[sensor] === "1" ? 0 : 1 });
  const info = module?.info ?? {};
  const names = Object.keys(status.sensors);
  const binary = names.filter((n) => info[n]?.binary ?? true);
  const numeric = names.filter((n) => info[n] && !info[n].binary);

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

      {binary.length > 0 && (
        <div className="sim-row">
          {binary.map((n) => (
            <button key={n} onClick={() => toggle(n)}>
              {toggleText(status.sensors[n] === "1", sensorLabel(n, info[n]), info[n]?.kind ?? "")}
            </button>
          ))}
        </div>
      )}
      {numeric.map((n) => (
        <NumericControl key={n} name={n} value={status.sensors[n]} info={info[n]} send={send} />
      ))}
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

function NumericControl({ name, value, info, send }: {
  name: string;
  value: string;
  info: NodeState["info"][string];
  send: (c: SimCommand) => void;
}) {
  const [text, setText] = useState("");
  const alarm = alarmValue(info);
  const set = (v: number) => send({ cmd: "set", sensor: name, value: v });
  return (
    <div className="sim-row numeric">
      <span className="sim-reading">
        {sensorLabel(name, info)} <strong>{value}{info.unit ? ` ${info.unit}` : ""}</strong>
      </span>
      <input
        type="number"
        value={text}
        placeholder={info.unit || "value"}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && text && set(Number(text))}
        aria-label={`${name} value`}
      />
      <button onClick={() => text && set(Number(text))}>Set</button>
      {info.normal !== undefined && <button className="secondary" onClick={() => set(info.normal!)}>Normal</button>}
      {alarm !== undefined && <button className="danger" onClick={() => set(alarm)}>Alarm</button>}
    </div>
  );
}

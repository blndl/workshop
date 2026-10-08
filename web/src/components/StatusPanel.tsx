import { STATE_LABEL } from "../format";
import type { StateSnapshot } from "../types";

export function StatusPanel({ state }: { state: StateSnapshot | null }) {
  if (!state) return <section className="card status muted">Waiting for alarm-core…</section>;
  return (
    <>
      {state.safety.length > 0 && (
        <section className={state.safety_silenced ? "card safety silenced" : "card safety"}>
          <div className="safety-label">SAFETY ALARM</div>
          {state.safety.map((a) => {
            const node = state.nodes[a.node];
            const label = node?.info[a.sensor]?.label ?? a.sensor;
            return (
              <div key={`${a.node}-${a.sensor}`}>
                {label}: <strong>{a.value}{a.unit ? ` ${a.unit}` : ""}</strong> · {node?.name ?? a.node} · for {Math.round(a.since_s)} s
              </div>
            );
          })}
          <div className="small">
            {state.safety_silenced
              ? "Silenced. It stays here until the reading is back to normal."
              : "Sounds whether or not the system is armed. Enter a code and press Disarm to silence it."}
          </div>
        </section>
      )}
      <section className={`card status state-${state.state}`}>
        <div className="status-label">{STATE_LABEL[state.state]}</div>
        <div className="status-reason">
          {state.reason}
          {state.node ? ` · ${state.node}` : ""}
        </div>
        {state.deadline_in != null && (
          <div className="status-countdown">
            {state.state === "entry_delay" ? "Alarm in " : "Armed in "}
            <strong>{Math.ceil(state.deadline_in)} s</strong>
          </div>
        )}
        {state.siren && <div className="siren">Siren on</div>}
        {state.log && (
          <div className="status-log" title={`head ${state.log.head}`}>
            Event log: {state.log.seq} records
          </div>
        )}
      </section>
    </>
  );
}

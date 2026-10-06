import { STATE_LABEL } from "../format";
import type { StateSnapshot } from "../types";

export function StatusPanel({ state }: { state: StateSnapshot | null }) {
  if (!state) return <section className="card status muted">Waiting for alarm-core…</section>;
  return (
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
  );
}

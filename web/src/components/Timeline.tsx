import { clock, describe } from "../format";
import type { AlarmEvent } from "../types";

export function Timeline({ events }: { events: AlarmEvent[] }) {
  return (
    <section className="card timeline">
      <h2>Events</h2>
      {events.length === 0 && <p className="muted">No events yet</p>}
      <ol>
        {events.map((e, i) => {
          const { text, severity } = describe(e);
          return (
            <li key={`${e.ts}-${e.seq ?? i}-${e.type}`} className={`ev ${severity}`}>
              <time>{clock(e.ts)}</time>
              <span>{text}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

import { useEffect, useState } from "react";
import { api } from "../api";

const DASHBOARD = "/d/alarm-overview/alarm";

/** The Grafana dashboard, embedded. Grafana runs with the `monitoring` profile. */
export function MetricsTab() {
  const [grafana, setGrafana] = useState<string | null | undefined>(undefined);
  const dark = useDarkMode();

  useEffect(() => {
    api.info().then((i) => setGrafana(i.grafana_url), () => setGrafana(null));
  }, []);

  if (grafana === undefined) return <section className="card muted">Loading…</section>;
  if (!grafana)
    return (
      <section className="card">
        <h2>Metrics</h2>
        <p>Grafana isn't running. Start the stack with monitoring:</p>
        <pre>scripts/sim.sh up</pre>
        <p className="muted small">
          (It's on by default; <code>NO_MONITORING=1</code> turns it off. When running the API by hand, set{" "}
          <code>GRAFANA_URL=http://127.0.0.1:3000</code>.)
        </p>
      </section>
    );

  const src = `${grafana}${DASHBOARD}?orgId=1&kiosk&refresh=10s&theme=${dark ? "dark" : "light"}`;
  return (
    <section className="metrics-tab">
      <div className="metrics-bar">
        <span className="muted small">Prometheus · Loki · PostgreSQL, through Grafana</span>
        <a href={`${grafana}${DASHBOARD}`} target="_blank" rel="noreferrer">
          Open in Grafana ↗
        </a>
      </div>
      <iframe key={src} src={src} title="Grafana metrics" className="metrics-frame" />
    </section>
  );
}

function useDarkMode(): boolean {
  const query = "(prefers-color-scheme: dark)";
  const [dark, setDark] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const m = window.matchMedia(query);
    const onChange = () => setDark(m.matches);
    m.addEventListener("change", onChange);
    return () => m.removeEventListener("change", onChange);
  }, []);
  return dark;
}

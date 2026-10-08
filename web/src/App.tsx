import { useEffect, useState } from "react";
import { api } from "./api";
import { Keypad } from "./components/Keypad";
import { Metrics } from "./components/Metrics";
import { MetricsTab } from "./components/MetricsTab";
import { NodeCard } from "./components/NodeCard";
import { SimPanel } from "./components/SimPanel";
import { StatusPanel } from "./components/StatusPanel";
import { Timeline } from "./components/Timeline";
import { usePoll } from "./usePoll";

const RSSI_POINTS = 120; // 2 minutes at one sample per second

type Tab = "overview" | "metrics";
const tabFromHash = (): Tab => (window.location.hash === "#metrics" ? "metrics" : "overview");

export function App() {
  const state = usePoll(api.state, 1000);
  const events = usePoll(() => api.events(500), 2000);
  const health = usePoll(api.health, 3000);
  const sim = usePoll(api.sim, 1000);
  const [rssi, setRssi] = useState<Record<string, number[]>>({});
  const [tab, setTab] = useState<Tab>(tabFromHash);

  // The tab lives in the URL (#metrics), so it survives a reload and can be linked.
  useEffect(() => {
    const onHash = () => setTab(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // Keep a rolling signal-strength history per node, one point per state update.
  useEffect(() => {
    const nodes = state.data?.nodes;
    if (!nodes) return;
    setRssi((prev) => {
      const next = { ...prev };
      for (const [name, n] of Object.entries(nodes)) {
        if (n.rssi == null) continue;
        next[name] = [...(prev[name] ?? []), n.online ? n.rssi : -90].slice(-RSSI_POINTS);
      }
      return next;
    });
  }, [state.data?.ts]);

  const connected = health.data?.mqtt_connected && !state.error;
  const nodes = Object.entries(state.data?.nodes ?? {}).sort(([a], [b]) => a.localeCompare(b));

  return (
    <div className="app">
      <header className="topbar">
        <h1>Alarm</h1>
        <span className={connected ? "pill ok" : "pill bad"}>
          {connected ? "connected" : state.error ? "API unreachable" : "alarm-core not responding"}
        </span>
        <nav className="tabs" aria-label="views">
          <a href="#overview" className={tab === "overview" ? "tab active" : "tab"}>Overview</a>
          <a href="#metrics" className={tab === "metrics" ? "tab active" : "tab"}>Metrics</a>
        </nav>
      </header>

      {tab === "metrics" ? (
        <MetricsTab />
      ) : (
      <>
      <main className="grid">
        <div className="col">
          <StatusPanel state={state.data} />
          <Keypad />
        </div>
        <div className="col">
          {nodes.map(([name, n]) => (
            <NodeCard key={name} name={name} node={n} rssiHistory={rssi[name] ?? []} />
          ))}
          <Metrics events={events.data ?? []} />
        </div>
        <div className="col">
          <Timeline events={(events.data ?? []).slice(0, 100)} />
        </div>
      </main>

      {sim.data?.enabled && <SimPanel nodes={sim.data.nodes} />}
      </>
      )}
    </div>
  );
}

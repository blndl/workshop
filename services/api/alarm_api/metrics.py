"""Prometheus metrics for the alarm, served at GET /metrics.

Two kinds:
- gauges read from the latest alarm/state at scrape time (state, per-module
  link, signal, sensors, database queue): always current, nothing to update;
- counters bumped from the event stream (events by type, state changes,
  security events, sensor changes).

The bridge never passes duress events (or replies) on, so no metric can
reveal a forced disarm: a duress disarm counts exactly like a normal one.
"""

from __future__ import annotations

import time

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client import CONTENT_TYPE_LATEST  # noqa: F401  (re-exported for app.py)
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

STATES = ("disarmed", "arming", "armed", "entry_delay", "triggered")


def _label(value, limit: int = 32) -> str:
    """Bound label values: they come from messages, and every new value is a new series."""
    return str(value)[:limit] if value is not None else ""


class _StateCollector:
    """Turns the latest alarm/state snapshot into gauges at scrape time."""

    def __init__(self, bridge):
        self.bridge = bridge

    def collect(self):
        b = self.bridge
        yield GaugeMetricFamily("alarm_mqtt_connected", "API connected to the broker (1/0)", value=int(b.connected))
        state, received = b.state, b.state_received_at
        if state is not None and received is not None:
            yield GaugeMetricFamily("alarm_state_age_seconds", "Seconds since alarm-core last published its state",
                                    value=time.time() - received)
            current = GaugeMetricFamily("alarm_state", "Current alarm state (1 for the current one)", labels=["state"])
            for s in STATES:
                current.add_metric([s], int(state.get("state") == s))
            yield current
            yield GaugeMetricFamily("alarm_siren", "Siren on (1/0)", value=int(bool(state.get("siren"))))
            yield GaugeMetricFamily("alarm_delay_remaining_seconds", "Exit/entry delay left, 0 if none",
                                    value=state.get("deadline_in") or 0)
            if state.get("log"):
                yield GaugeMetricFamily("alarm_log_records", "Records in alarm-core's tamper-evident log",
                                        value=state["log"].get("seq", 0))
            yield from self._nodes(state.get("nodes") or {})
        yield from self._database()

    def _nodes(self, nodes: dict):
        online = GaugeMetricFamily("alarm_node_online", "Module link up (1/0)", labels=["node"])
        rssi = GaugeMetricFamily("alarm_node_rssi_dbm", "Module Wi-Fi signal (dBm)", labels=["node"])
        uptime = GaugeMetricFamily("alarm_node_uptime_seconds", "Module uptime", labels=["node"])
        seen = GaugeMetricFamily("alarm_node_seen_ago_seconds", "Seconds since the module was last heard", labels=["node"])
        sensor = GaugeMetricFamily("alarm_node_sensor_active", "Sensor active (1) or not (0)", labels=["node", "sensor"])
        rejected = GaugeMetricFamily("alarm_node_rejected_messages", "Forged/replayed messages rejected since alarm-core started",
                                     labels=["node", "kind"])
        for name, n in nodes.items():
            node = _label(name)
            online.add_metric([node], int(bool(n.get("online"))))
            if n.get("rssi") is not None:
                rssi.add_metric([node], n["rssi"])
            if n.get("uptime") is not None:
                uptime.add_metric([node], n["uptime"])
            if n.get("seen_ago") is not None:
                seen.add_metric([node], n["seen_ago"])
            for s, v in (n.get("sensors") or {}).items():
                sensor.add_metric([node, _label(s)], int(v == "1"))
            for kind, count in (n.get("security") or {}).items():
                rejected.add_metric([node, _label(kind)], count)
        yield from (online, rssi, uptime, seen, sensor, rejected)

    def _database(self):
        store = self.bridge.store
        if store is None:
            return
        yield GaugeMetricFamily("alarm_db_connected", "Event store connected to PostgreSQL (1/0)", value=int(store.connected))
        yield GaugeMetricFamily("alarm_db_pending_events", "Events waiting to be written", value=store.pending)
        yield CounterMetricFamily("alarm_db_written_events", "Events written to PostgreSQL", value=store.written)
        yield CounterMetricFamily("alarm_db_dropped_events", "Events dropped because the queue was full", value=store.dropped)


class Metrics:
    def __init__(self, bridge):
        # A registry per app (not the global one), so tests can build several apps.
        self.registry = CollectorRegistry()
        r = self.registry
        self.events = Counter("alarm_events", "Events from alarm-core, by type", ["type"], registry=r)
        self.state_changes = Counter("alarm_state_changes", "State changes, by new state", ["state"], registry=r)
        self.security = Counter("alarm_security_events", "Rejected forged/replayed messages", ["node", "kind"], registry=r)
        self.sensor_changes = Counter("alarm_sensor_changes", "Sensor changes", ["node", "sensor", "value"], registry=r)
        self.http = Histogram("alarm_api_request_duration_seconds", "API request duration",
                              ["method", "route", "status"], registry=r,
                              buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5))
        r.register(_StateCollector(bridge))
        bridge.listeners.append(self.on_event)

    def on_event(self, e: dict) -> None:
        """Called by the bridge for every real event (never duress, never replies)."""
        t = e.get("type")
        self.events.labels(_label(t)).inc()
        if t == "state":
            self.state_changes.labels(_label(e.get("state"))).inc()
        elif t == "security":
            self.security.labels(_label(e.get("node")), _label(e.get("kind"))).inc()
        elif t == "sensor":
            self.sensor_changes.labels(_label(e.get("node")), _label(e.get("sensor")), _label(e.get("value"))).inc()

    def render(self) -> bytes:
        return generate_latest(self.registry)

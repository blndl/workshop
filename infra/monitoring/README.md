# monitoring

Metrics, logs and history for the box, in Grafana. Started by `scripts/sim.sh up` (or `hub`) with the `monitoring` profile; `NO_MONITORING=1` skips it.

**Open it:** the dashboard's **Metrics** tab (http://127.0.0.1:8000/#metrics), or Grafana itself at http://127.0.0.1:3000. Viewing needs no login; editing needs the `admin` account (password in `.secrets/dev.json` under `grafana`).

```
 api /metrics ──────────────┐
 node-exporter (the box) ───┼──▶ Prometheus ──┐
 cAdvisor (each container) ─┘                 │
 container logs ──▶ Alloy ──▶ Loki ───────────┼──▶ Grafana ──▶ Metrics tab
 PostgreSQL (event history) ──────────────────┘
```

| Container | Role | Config |
|---|---|---|
| `prometheus` | Scrapes and stores metrics (15 days) | [prometheus/prometheus.yml](prometheus/prometheus.yml) |
| `grafana` | Dashboards | [grafana/](grafana/): data sources and the dashboard, provisioned from files |
| `loki` | Stores logs | image defaults |
| `alloy` | Collects the containers' logs for Loki, **dropping any line that mentions duress** | [alloy/config.alloy](alloy/config.alloy) |
| `node-exporter` | CPU, memory, disk of the box | |
| `cadvisor` | CPU and memory of each container | |

Only Grafana is published, on 127.0.0.1:3000. The others are reachable only on the `core` network, and `scripts/sim.sh probe` checks that the house network can't reach the database.

## The dashboard

[grafana/dashboards/alarm.json](grafana/dashboards/alarm.json), five sections:

| Section | Panels | Source |
|---|---|---|
| Alarm | State, siren, alarms and rejected messages in the last 24 h, modules online, log size, state over time | Prometheus, PostgreSQL |
| Modules | Wi-Fi signal, link, sensors over time, rejected messages per minute, seconds since last heard (red line at the 3 s watchdog) | Prometheus |
| Platform | Events per minute by type, API latency (p95), event-database queue, CPU and memory per container, the box's CPU/memory/disk | Prometheus |
| History | Alarms and attacks over time, events by type, rejected messages by module, latest events | PostgreSQL (read-only `grafana_ro` role) |
| Logs | All alarm services' logs, filterable by service and searchable | Loki |

The JSON file is the source of truth (`allowUiUpdates: false`). To change the dashboard: edit it in Grafana as admin, use *Export → JSON*, replace the file, and commit.

## Metrics exported by the API

From [services/api/alarm_api/metrics.py](../../services/api/alarm_api/metrics.py), at `GET /metrics`:

| Metric | Labels | Meaning |
|---|---|---|
| `alarm_state` | `state` | 1 for the current state |
| `alarm_siren`, `alarm_delay_remaining_seconds`, `alarm_log_records` | | Siren, countdown, log size |
| `alarm_node_online`, `alarm_node_rssi_dbm`, `alarm_node_uptime_seconds`, `alarm_node_seen_ago_seconds` | `node` | Per module |
| `alarm_node_sensor_active` | `node`, `sensor` | 1 while a sensor is active |
| `alarm_node_rejected_messages` | `node`, `kind` | Rejected messages since alarm-core started |
| `alarm_events_total` | `type` | Events from alarm-core |
| `alarm_state_changes_total` | `state` | State changes |
| `alarm_security_events_total` | `node`, `kind` | Rejected forged/replayed messages |
| `alarm_sensor_changes_total` | `node`, `sensor`, `value` | Sensor changes |
| `alarm_db_connected`, `alarm_db_pending_events`, `alarm_db_written_events_total`, `alarm_db_dropped_events_total` | | Event database |
| `alarm_api_request_duration_seconds` | `method`, `route`, `status` | API latency |
| `alarm_mqtt_connected`, `alarm_state_age_seconds` | | Is the API seeing alarm-core? |

New modules' sensors show up automatically (labels, not new metric names).

## Privacy and security notes

- **No duress anywhere:** not in metrics (the API never passes those events on), not in the database, not in Loki (Alloy drops the lines). They remain only in `docker logs alarm-core` on the box itself. `test_prometheus_metrics` checks the metrics side.
- **Anonymous read-only Grafana**, embeddable in the dashboard. That's fine on 127.0.0.1; with the dashboard login (task D2) it should switch to Grafana's auth proxy, or require a login.
- **Alloy and cAdvisor can read the Docker API** (`docker.sock`). That access can see every container, so these containers are part of the box's trusted base; mention them in the threat model.
- **Dev-only passwords:** `grafana_ro` uses `grafana-ro-dev`; the Grafana admin password comes from `.secrets/dev.json`.
- **Resources:** about 600 MB of RAM for the monitoring containers (Grafana alone is about 300 MB). Fine on a laptop or VM; on a real Pi, consider dropping cAdvisor and Loki.

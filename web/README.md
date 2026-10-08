# web

The dashboard: React + TypeScript, built with Vite. It talks only to the API (`services/api`), which also serves the built files.

```
src/
  App.tsx              layout, polling, signal history
  api.ts, types.ts     API client and response shapes
  usePoll.ts           refresh every N ms
  format.ts            event descriptions, durations
  sensors.ts           how to display a sensor from its description
  components/
    StatusPanel        safety-alarm banner, state, countdown, siren, log size
    Keypad             arm / disarm with a code
    NodeCard           one module, from its description: on/off tiles, numeric readings + charts, link
    Metrics            counts of alarms, attacks, link losses, wrong codes, photos
    Timeline           recent events, coloured by severity
    SimPanel           DEV ONLY: drive the simulated modules (any sensor), see their LED and buzzer
    CameraTab          the Camera tab: live feed, live view, vision stats, health, photos with detection boxes
    MetricsTab         the Metrics tab: Grafana embedded (needs the monitoring profile)
```

## Run it

Start the backend (from the repo root, broker running):

```bash
.venv/bin/python -m alarm_core run --exit-delay 5 --entry-delay 10
.venv/bin/python -m alarm_api --sim                          # --sim shows the simulator panel
.venv/bin/python -m alarm_sim node --node door-1 --headless  # one per module in config/modules.yaml
.venv/bin/python -m alarm_sim node --node env-1 --headless
```

Then either:

```bash
cd web && npm install && npm run build    # then open http://127.0.0.1:8000
cd web && npm run dev                     # live reload on http://localhost:5173 while editing
```

`npm run dev` forwards `/api` to the API on port 8000.

Module cards and simulator controls are drawn from each module's description (`info` in `/api/state`): on/off tiles for binary sensors, readings with their limit and a chart for numeric ones, and a safety-alarm banner. A new module needs no front-end change ([docs/modules.md](../docs/modules.md)).

## Simulator panel

Shown only when the API runs with `--sim`. For each simulated module: flip its on/off sensors, set numeric readings (or jump to **Normal** / **Alarm**), jam the Wi-Fi for 6 s, reboot, and launch any of the 8 attacks. The fake device's LED and buzzer show what alarm-core commands it to do.

It works through dev-only MQTT topics (`sim/<node>/cmd` and `sim/<node>/status`, see `simulator/alarm_sim/control.py`). A real ESP has no such channel; remove the `sim/` lines from the broker ACL on a real deployment.

## Notes

- **Polling, not WebSockets:** state every 1 s, events every 2 s. WebSocket push is task D3.
- **No login yet (D2):** the API only listens on 127.0.0.1.
- **The timeline and metrics** cover the events the API has seen since it started (up to 500). Full history from the event log is part of D3.
- **Photos** aren't shown yet: they need login first (D3).

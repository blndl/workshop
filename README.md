# workshop

**A modular, self-hosted security platform** that protects a site against intrusion and environmental hazards, cuts false alarms with on-site AI, and is built to resist attacks on itself.

It's for any site that needs alarm monitoring without handing its data to a cloud provider: **offices, shops, small business premises, warehouses, technical and server rooms, labs, and homes**. One core supervises any number of field modules (door and motion, gas and temperature, more by configuration), with one dashboard, one audit trail and one alerting channel.

## Why it's different

| | |
|---|---|
| **Secure by design** | Every message between a module and the core is encrypted and authenticated (ChaCha20-Poly1305) with replay protection. Jamming, cut cables and a smashed module trigger the alarm (fail-secure). Network segmentation means a compromised device on the site network can reach the message broker and nothing else. |
| **Fewer false alarms** | On-site person detection (YOLOv8n) verifies motion before it counts: a cat, a curtain or a light change is dismissed. False alarms waste staff time and, where a monitoring company or guard is called out, cost money. The platform counts how many it avoided. |
| **Intrusion and safety in one** | Intrusion alarms (entry delay, instant zones, tamper) run alongside safety alarms (gas, overheating…) that sound whether or not the system is armed. |
| **Evidence you can trust** | Every event and every photo is recorded in a tamper-evident, hash-chained log. Edited or deleted records and modified photos are detected, which matters when footage is used after an incident. |
| **Modular** | A new kind of module is a description in [`config/modules.yaml`](config/modules.yaml), not new code: the core treats each sensor by its role ([docs/modules.md](docs/modules.md)). |
| **Privacy by design** | Cameras are off while disarmed. Viewing them is time-limited and logged, photos are deleted after 30 days, and nothing leaves the site unless you choose to. That's a strong base for GDPR compliance. |
| **Self-hosted and observable** | Runs as Docker containers on any Linux machine (a small server, a VM, a mini PC, a Raspberry Pi). Metrics, logs and history in Grafana; alerts to phones through a self-hosted ntfy server. |

## Architecture

**Modules** (ESP8266 boards, or simulated ones) talk over the site's Wi-Fi to **the core**, a set of Docker services:

```
 site network (iot)                             the core (Docker)
 ┌──────────────┐  encrypted MQTT   ┌──────────────────────────────────────────────────────┐
 │ door-1       │◀────────────────▶ │ Mosquitto ── alarm-core (state machine, audit log)    │
 │ env-1        │   protocol v1     │                │                                     │
 │ (more…)      │                   │   api + dashboard · camera · detector · notifier      │
 └──────────────┘                   │   PostgreSQL · monitoring: Prometheus, Loki, Grafana │
                                    └──────────────────────────────────────────────────────┘
                                         browser :8000      phones (ntfy) :8080
```

Two example modules come with it, both simulated:

| Module | Sensors | What it shows |
|---|---|---|
| **door-1**, entrance | door (entry), motion (entry, verified by the camera), lid (tamper) | Intrusion: entry delay, AI verification, alarm, siren |
| **env-1**, technical room / kitchen | gas and temperature (safety), humidity (telemetry), lid (tamper) | Safety alarms whether or not the system is armed |

## Project status

This is a **working prototype**, developed as an EPSI M1 project. The core, the protocol, the AI verification, the dashboard and the monitoring all run, are tested (190 Python tests, C++ test vectors, an end-to-end CI run of the whole stack) and can be demonstrated. The field modules are **simulated** (Python, and the C++ edge simulator).

Not there yet, and needed before a real deployment:
- **User login with 2FA and roles.** The dashboard currently listens on localhost only.
- **A hardened host and secure remote access:** OS hardening, firewall, Tailscale.
- **Firmware on real hardware.** The C++ protocol is ready for it.
- **A formal threat model, a pentest and a GDPR review.**

The platform makes **no claim of compliance with alarm standards** (EN 50131, NF&A2P) and has **no certification**. See [Status](#status) for the roadmap.

## Quick start: everything in Docker

Needs Docker Desktop (or Docker on Linux). No Python or Node setup required.

```bash
scripts/dev-secrets.sh        # once: keys for every module, passwords, dev codes
scripts/dev-ntfy.sh           # once: alert accounts (prints the phone/browser login)
scripts/sim.sh up             # builds the image, fetches the AI model; starts the core, both modules, monitoring
```

Open **http://127.0.0.1:8000**.

- **Intrusion:** arm with `1234`, then click **Open door** in the simulator panel at the bottom. After the 10 s entry delay the alarm triggers, the modules' buzzers turn on, and an alert with a photo arrives at http://localhost:8080.
- **Safety alarm:** click **Alarm** next to Gas in env-1's simulator controls, even while disarmed. The buzzers sound and an urgent alert goes out. Entering a code and pressing **Disarm** silences it; **Normal** clears it.
- **Attacks:** pick one in a module's simulator controls (spoof, replay…) and click **Run attack**. It's rejected and counted, and the alarm isn't fooled.
- **Camera tab:** the live feed while armed (or a 2-minute **live view** while disarmed, recorded in the log), the photos with what the AI saw (boxes, "person 89%"), an integrity check of each photo against the log, and how many false alarms the person check avoided.
- **Vision:** door-1's motion sensor only counts if the camera sees a person. With the default fake camera nobody is in the picture, so **Trigger motion** while armed is *dismissed*, like a cat. To see it confirmed, put photos with people in `data/test-images/` and run `CAMERA_SOURCE=--images=/app/data/test-images scripts/sim.sh up`.
- **Metrics tab:** Grafana, with signal and readings per module, attacks, events, the database, CPU and memory for every container, the history, and all the logs ([infra/monitoring](infra/monitoring/README.md)).

| Command | What it does |
|---|---|
| `scripts/sim.sh up` | Core + both simulated modules + monitoring (5 s exit / 10 s entry delay, simulator panel on) |
| `scripts/sim.sh hub` | Core + monitoring only, for real ESPs (30 s delays, no simulator panel) |
| `NO_MONITORING=1 scripts/sim.sh up` | Same as `up` without Prometheus/Grafana/Loki (saves about 600 MB of RAM) |
| `ENV_NODE=cpp ENV_SCENARIO=gas_leak scripts/sim.sh up` | env-1 from the **C++ edge simulator** over the encrypted protocol, playing a scenario (`gas_leak`, `overheat`, `combined_attack`…) |
| `scripts/sim.sh down` | Stop everything (the event log, photos, database and accounts are kept) |
| `scripts/sim.sh status` | Show the alarm state |
| `scripts/sim.sh arm 1234` / `disarm 1234` | Arm or disarm from the terminal |
| `scripts/sim.sh verify` | Check that the event log and photos haven't been tampered with |
| `scripts/sim.sh probe` | Check that a device on the site network can only reach the broker |
| `scripts/sim.sh logs [service]` | Follow the logs: all, or one service (`alarm-core`, `api`, `door-1`, `env-1`, `notifier`…) |
| `scripts/sim.sh ps` | List the running containers |

### Addresses and credentials

| What | Where | Login |
|---|---|---|
| Dashboard + API | http://127.0.0.1:8000 (API docs at `/docs`) | none yet (login is task D2), so it listens on localhost only |
| Grafana | http://127.0.0.1:3000, also in the dashboard's Metrics tab | viewing: none · admin: password in `.secrets/dev.json` → `grafana` |
| Alerts (ntfy) | http://localhost:8080, or the ntfy phone app | `phone` / password in `.secrets/dev.json` → `ntfy` |
| MQTT broker | 127.0.0.1:1883 (`MQTT_BIND=0.0.0.0` for real ESPs on the network) | one account per module and service |
| Alarm codes | dev only | **`1234`** user code · **`9999`** duress code (disarms normally, silently alerts: for a staff member or resident forced to disarm) |

Everything secret lives in `.secrets/` (keys, passwords, codes), created by `scripts/dev-secrets.sh` and never committed. Ports, settings, real ESPs and the webcam on Linux: [infra/docker/README.md](infra/docker/README.md).

## Adding a module

1. Describe it in [`config/modules.yaml`](config/modules.yaml): its sensors, each with a kind and a role (`entry`, `instant`, `tamper`, `safety` or `telemetry`), and thresholds for numeric sensors.
2. `scripts/dev-secrets.sh`, then `docker compose -f infra/docker/compose.yml restart mosquitto`.
3. To simulate it, add a container to the `sim` profile in [compose.yml](infra/docker/compose.yml) (copy `env-1`), then `scripts/sim.sh up`.

The dashboard, Grafana and alerts pick it up from its description. Full guide: [docs/modules.md](docs/modules.md).

**Every module in `modules.yaml` must be online to arm**, so remove the ones you don't run.

## Developing: services on your machine

To edit a service and run it directly (or use the Mac's real webcam), start only the broker, ntfy and PostgreSQL in Docker, and run the services in terminals:

```bash
python3 -m venv .venv
.venv/bin/pip install -e 'protocol/python[mqtt,dev]' -e 'simulator[dev]' -e 'services/alarm-core[dev]' \
                      -e 'services/camera[dev,webcam]' -e 'services/notifier[dev]' -e 'services/api[dev]' \
                      -e 'services/detector[dev]'
cd web && npm install && npm run build && cd ..

docker compose -f infra/docker/compose.yml up -d        # broker + ntfy + PostgreSQL only
```

| Terminal | Command | Role |
|---|---|---|
| 1 | `.venv/bin/python -m alarm_core run --exit-delay 5 --entry-delay 10` | the alarm's brain |
| 2 | `.venv/bin/python -m alarm_api --sim` | dashboard on http://127.0.0.1:8000 |
| 3 | `.venv/bin/python -m alarm_sim node --node door-1 --headless` | simulated door module (drop `--headless` to type commands) |
| 4 | `.venv/bin/python -m alarm_sim node --node env-1 --headless` | simulated environment module |
| 5 | `.venv/bin/python -m alarm_camera run` (or `--fake run`) | snapshots while armed |
| 5b | `.venv/bin/python -m alarm_detector run` | person detection (`scripts/get-model.sh` first) |
| 6 | `.venv/bin/python -m alarm_notifier run` | phone alerts |

Run **either** this **or** `scripts/sim.sh up`, never both: they'd share port 8000, and two copies of each module would fight over the same identity. Started this way, the API keeps events in memory only (it saves to PostgreSQL when `DATABASE_URL` is set) and the Metrics tab stays empty (it needs `GRAFANA_URL`).

For live reload of the dashboard: `cd web && npm run dev`, then open http://localhost:5173.

## Tests

```bash
.venv/bin/pytest protocol/python simulator services/alarm-core services/camera services/detector services/notifier services/api
.venv/bin/python -m alarm_sim selftest      # attack and failure scenarios
cd web && npm run build                     # includes the TypeScript check
```

C++ (in Docker, no local toolchain needed):

```bash
docker build -f protocol/cpp/Dockerfile.test protocol                          # C++ protocol vs test vectors
docker build -f IA_VISON/edge-simulator/Dockerfile.alarm -t alarm-node .       # edge simulator + alarm-node
```

CI runs all of this on every push. It also starts the whole stack in Docker, waits until every module is online, arms through the API, and runs the network segmentation probe.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `port is already allocated` / `address already in use` on 8000 | Something else (often a terminal-run `alarm_api`) uses it. Stop it, or `API_PORT=8001 scripts/sim.sh up`. |
| Arming refused: `<module> offline` | That module isn't running. Start it, or remove it from `config/modules.yaml` and restart alarm-core. |
| A module never comes online, `not authorised` in the broker log | Its account is missing. `scripts/dev-secrets.sh`, then restart Mosquitto. |
| alarm-core exits: `no key for module(s)…` | Same: `scripts/dev-secrets.sh`, restart Mosquitto, then `scripts/sim.sh up`. |
| alarm-core exits with a `modules.yaml` error | The description is invalid; the message names the module and sensor ([rules](docs/modules.md)). |
| Alerts refused with HTTP 401 | ntfy accounts were recreated: rerun `scripts/dev-ntfy.sh`, which restarts the notifier. |
| `PermissionError` on `.secrets/dev.json` in a container (Linux) | Start through `scripts/sim.sh`, which runs the containers as your user, or export `HOST_UID=$(id -u) HOST_GID=$(id -g)`. |
| Dashboard says "no dashboard build" | `cd web && npm install && npm run build` (only when running the API outside Docker). |

## Documentation

| Topic | Where |
|---|---|
| Modules: description format, roles, adding one | [docs/modules.md](docs/modules.md) |
| Protocol between modules and core | [protocol/spec.md](protocol/spec.md) · C++: [protocol/cpp](protocol/cpp/README.md) |
| C++ edge simulator as env-1 | [IA_VISON/edge-simulator](IA_VISON/edge-simulator/README.md) |
| Alarm logic, events, tamper-evident log | [services/alarm-core](services/alarm-core/README.md) |
| Simulator, attacks, scenarios | [simulator](simulator/README.md) |
| API, event database | [services/api](services/api/README.md) |
| Camera, person detection, notifier | [services/camera](services/camera/README.md) · [services/detector](services/detector/README.md) · [services/notifier](services/notifier/README.md) |
| Dashboard | [web](web/README.md) |
| Docker stack, networks, ports | [infra/docker](infra/docker/README.md) |
| Monitoring | [infra/monitoring](infra/monitoring/README.md) |

## Folders

| Folder | Contents |
|---|---|
| `config/` | `modules.yaml`: the modules plugged into the core |
| `protocol/` | Module↔core protocol over MQTT: spec, test vectors, Python and C++ implementations |
| `IA_VISON/` | Browser vision demo, and the C++ edge simulator (`alarm-node`: env-1 in C++) |
| `simulator/` | Simulated modules, attacks, scenarios |
| `services/alarm-core/` | State machine, codes, tamper-evident event log |
| `services/api/` | FastAPI backend: dashboard API, metrics, event database |
| `services/camera/` | Snapshots while armed |
| `services/notifier/` | Phone alerts through ntfy |
| `services/detector/` | Person detection (YOLOv8n) on the camera's photos |
| `web/` | React dashboard |
| `infra/` | Docker image and Compose stack, monitoring; Ansible and VPN later |
| `scripts/` | `dev-secrets.sh`, `dev-ntfy.sh`, `sim.sh` |
| `docs/` | Module guide; report later |
| `firmware/`, `hardware/`, `cloud/`, `security/` | To do: ESP firmware, wiring, off-site parts, threat model and pentest |
| `.secrets/`, `data/`, `models/` | Created at run time, never committed: secrets, event log and photos, the AI model |

## Status

| Phase | Content | Status |
|---|---|---|
| 0. Stabilise | CI green, PostgreSQL merged, branch protection, integrate the YOLO branch | Mostly done (YOLO integration pending) |
| 1. Module framework | `modules.yaml`, sensor roles, safety alarms, generic simulator and dashboard | **Done** |
| 2. Vision | Detector service (YOLOv8n), "motion needs a person" rule, Camera tab, evaluation tool | **Done** (the evaluation dataset is yours to build: `alarm_detector evaluate`) |
| 3. Environment | C++ protocol (test-vector exact), the edge simulator as env-1, safety scenarios | **Done** (next: the same code on a real ESP) |
| 4. Platform | Login + 2FA, live updates, photos in the dashboard, the core on a hardened VM, Tailscale | Started: API, dashboard, Docker, PostgreSQL and monitoring done |
| 5. Security and report | Threat model per module, pentest, GDPR, demo | To do |

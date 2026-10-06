# workshop

A home security system that is itself hard to attack, and uses AI to cut false alarms.

A sensor node (ESP8266, or the simulator) talks over Wi-Fi to "the box": a set of Docker services that can run on any Linux machine (a VM, an old PC, a Raspberry Pi).

| Folder | Contents |
|---|---|
| `protocol/` | ESP↔box protocol over MQTT: spec, test vectors, Python codec |
| `simulator/` | Simulated ESP nodes, attacks, scenarios |
| `services/alarm-core/` | State machine, codes, tamper-evident event log |
| `services/api/` | FastAPI backend for the dashboard |
| `services/camera/` | Snapshots while armed |
| `services/notifier/` | Phone alerts through ntfy |
| `services/detector/` | Person detection (to do) |
| `web/` | React dashboard |
| `firmware/` | ESP8266 firmware (to do) |
| `infra/` | Docker image and Compose stack; Ansible, monitoring, VPN later |
| `scripts/` | Secrets generation, ntfy setup, `sim.sh` |
| `cloud/`, `security/`, `hardware/`, `docs/` | Off-site parts, threat model and pentest, wiring, report |

## Quick start: everything in Docker

Needs Docker Desktop (or Docker on Linux). No Python or Node setup required.

```bash
scripts/dev-secrets.sh        # once: keys, passwords, dev codes (1234 user, 9999 duress)
scripts/dev-ntfy.sh           # once: alert accounts (prints the phone/browser login)
scripts/sim.sh up             # builds the image, starts the box + a simulated ESP
```

Open **http://127.0.0.1:8000**. Arm with `1234`, then click **Open door** in the simulator panel at the bottom: after the 10 s entry delay the alarm triggers, the simulated ESP's buzzer turns on, and an alert with a photo arrives at http://localhost:8080.

| Command | What it does |
|---|---|
| `scripts/sim.sh up` | Start the box + simulated ESP (5 s exit / 10 s entry delay, simulator panel on) |
| `scripts/sim.sh hub` | Start the box only, for a real ESP (30 s delays, no simulator panel) |
| `scripts/sim.sh down` | Stop everything (the event log, photos and alert accounts are kept) |
| `scripts/sim.sh status` | Show the alarm state |
| `scripts/sim.sh arm 1234` / `disarm 1234` | Arm or disarm from the terminal |
| `scripts/sim.sh verify` | Check that the event log and photos haven't been tampered with |
| `scripts/sim.sh probe` | Check that a device on the house Wi-Fi can only reach the broker |
| `scripts/sim.sh logs [service]` | Follow the logs: all, or one of `alarm-core`, `api`, `camera`, `notifier`, `door-1` |
| `scripts/sim.sh ps` | List the running containers |

Settings and details (ports, real ESP, webcam on Linux): [infra/docker/README.md](infra/docker/README.md).

## Developing: services on your machine

To edit a service and run it directly (or use the Mac's real webcam), start only the broker and ntfy in Docker and run the services in terminals:

```bash
python3 -m venv .venv
.venv/bin/pip install -e 'protocol/python[mqtt,dev]' -e 'simulator[dev]' -e 'services/alarm-core[dev]' \
                      -e 'services/camera[dev,webcam]' -e 'services/notifier[dev]' -e 'services/api[dev]'
cd web && npm install && npm run build && cd ..

docker compose -f infra/docker/compose.yml up -d        # broker + ntfy only
```

| Terminal | Command | Role |
|---|---|---|
| 1 | `.venv/bin/python -m alarm_core run --exit-delay 5 --entry-delay 10` | the alarm's brain |
| 2 | `.venv/bin/python -m alarm_api --sim` | dashboard on http://127.0.0.1:8000, API docs at `/docs` |
| 3 | `.venv/bin/python -m alarm_sim node --node door-1 --headless` | the simulated ESP (drop `--headless` to type commands) |
| 4 | `.venv/bin/python -m alarm_camera run` (or `--fake run`) | snapshots while armed |
| 5 | `.venv/bin/python -m alarm_notifier run` | phone alerts |

Don't run these and `scripts/sim.sh up` at the same time: both would use port 8000 and two `door-1` nodes would fight over the same identity. Stop one before starting the other.

For live reload of the dashboard: `cd web && npm run dev`, then open http://localhost:5173.

## Tests

```bash
.venv/bin/pytest protocol/python simulator services/alarm-core services/camera services/notifier services/api
.venv/bin/python -m alarm_sim selftest
cd web && npm run build       # includes the TypeScript check
```

CI runs all of this on every push.

Details: [protocol](protocol/spec.md) · [simulator](simulator/README.md) · [alarm-core](services/alarm-core/README.md) · [api](services/api/README.md) · [camera](services/camera/README.md) · [notifier](services/notifier/README.md) · [dashboard](web/README.md) · [docker](infra/docker/README.md)

## Phases

1. **Core:** protocol, simulator, state machine, snapshots, ntfy alerts (done)
2. **Platform:** API + dashboard (done), Docker stack (in progress), login with 2FA, CI
3. **AI:** person detection with measured false-positive reduction, event summaries
4. **Security:** threat model, hardening + Lynis on the box, pentest, GDPR
5. **Stretch:** firmware on a real ESP, anomaly detection, Ansible, dead-man's switch, off-site backup

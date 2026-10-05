# workshop

A home security box that is itself hard to attack, and uses AI to cut false alarms.

| Folder | Contents |
|---|---|
| `firmware/` | ESP8266 sensor firmware |
| `protocol/` | ESP↔Pi serial protocol spec + shared codec (HMAC, counters) |
| `simulator/` | Fake ESP over a virtual serial port, for dev and CI |
| `services/alarm-core/` | Pi serial reader + alarm state machine |
| `services/api/` | FastAPI backend (auth, 2FA, RBAC, WebSockets) |
| `services/detector/` | Person detection + evaluation |
| `services/notifier/` | Alerts and AI summaries |
| `web/` | Dashboard / PWA |
| `infra/` | Docker Compose, Ansible, monitoring, VPN |
| `cloud/` | Dead-man's switch, off-site evidence |
| `security/` | Threat model, pentest, hardening reports |
| `hardware/` | Wiring, BOM, enclosure |
| `docs/` | Report, GDPR, demo script |

## Quick start

```bash
# install everything and run all tests (offline, no Docker needed)
python3 -m venv .venv
.venv/bin/pip install -e 'protocol/python[mqtt,dev]' -e 'simulator[dev]' -e 'services/alarm-core[dev]' \
                      -e 'services/camera[dev,webcam]' -e 'services/notifier[dev]'
.venv/bin/pytest protocol/python simulator services/alarm-core services/camera services/notifier
.venv/bin/python -m alarm_sim selftest
```

## Running the whole system (simulated sensors)

```bash
scripts/dev-secrets.sh                                   # once: keys, passwords, dev codes
docker compose -f infra/docker/compose.dev.yml up -d     # Mosquitto + ntfy
scripts/dev-ntfy.sh                                      # once: ntfy accounts + phone setup
```

Then one terminal per service:

| Terminal | Command | Role |
|---|---|---|
| 1 | `.venv/bin/python -m alarm_core run --exit-delay 5 --entry-delay 10` | the alarm's brain |
| 2 | `.venv/bin/python -m alarm_camera run` (or `--fake run`) | snapshots while armed |
| 3 | `.venv/bin/python -m alarm_notifier run` | phone alerts |
| 4 | `.venv/bin/python -m alarm_sim node` | the simulated ESP: type `door 1`, `jam 6`, `attack spoof`… |
| 5 | `.venv/bin/python -m alarm_core ctl arm 1234` | arm / disarm (`9999` = duress) / status |

Arm, wait 5 s, type `door 1` in terminal 4, wait 10 s: the alarm triggers, the node's buzzer turns on, and your phone gets an urgent alert with a photo. Afterwards, `.venv/bin/python -m alarm_core verify-log --snapshots` checks that the log and photos haven't been tampered with.

Details: [simulator](simulator/README.md) · [alarm-core](services/alarm-core/README.md) · [camera](services/camera/README.md) · [notifier](services/notifier/README.md) · [protocol](protocol/spec.md)

## Phases

1. **Core:** box, firmware, state machine, snapshots, Telegram alerts
2. **Platform:** Docker Compose, API + dashboard, DB, 2FA, simulator + CI
3. **AI:** person detection with measured false-positive reduction, event summaries
4. **Security:** threat model, HMAC serial link, hardening + Lynis, tamper-evident logs, pentest
5. **Stretch:** anomaly detection, Ansible, dead-man's switch, off-site backup, OTA

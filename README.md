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
# protocol + simulator, offline
python3 -m venv .venv && .venv/bin/pip install -e protocol/python -e 'simulator[dev]'
.venv/bin/pytest protocol/python simulator
.venv/bin/python -m alarm_sim selftest

# live, over a real MQTT broker (needs Docker)
scripts/dev-secrets.sh
docker compose -f infra/docker/compose.dev.yml up -d
```

See [simulator/README.md](simulator/README.md) for the hub and interactive node.

## Phases

1. **Core:** box, firmware, state machine, snapshots, Telegram alerts
2. **Platform:** Docker Compose, API + dashboard, DB, 2FA, simulator + CI
3. **AI:** person detection with measured false-positive reduction, event summaries
4. **Security:** threat model, HMAC serial link, hardening + Lynis, tamper-evident logs, pentest
5. **Stretch:** anomaly detection, Ansible, dead-man's switch, off-site backup, OTA

# docker

The whole alarm system as Docker containers. The same files run on a laptop, a Linux VM or any Linux box.

```
Dockerfile          one image (alarm) for every service, with the dashboard built in
compose.yml         the stack, in profiles
mosquitto/          broker config + ACL (who may publish/subscribe where)
ntfy/server.yml     alert server config
```

Usually you don't call Compose directly: [`scripts/sim.sh`](../../scripts/sim.sh) wraps it (see the root README).

## Profiles

| Profile | Containers | Started by |
|---|---|---|
| (none) | `mosquitto`, `ntfy` | `docker compose -f infra/docker/compose.yml up -d`: for running the services on your machine |
| `hub` | + `alarm-core`, `api`, `camera`, `notifier` | `scripts/sim.sh hub`: the box, waiting for a real ESP |
| `sim` | + `door-1` (simulated ESP) | `scripts/sim.sh up` (together with `hub`) |
| `probe` | `probe` (runs once) | `scripts/sim.sh probe` |

## Networks

```
  iot network (the house Wi-Fi)          core network (inside the box)
 ┌───────────────────────────┐         ┌──────────────────────────────────────┐
 │  door-1 (simulated ESP)   │         │  alarm-core   api   camera   notifier │
 │  probe                    ├─ mosquitto ─┤             ntfy                    │
 └───────────────────────────┘         └──────────────────────────────────────┘
```

Mosquitto is the only container on both networks. A device on the house Wi-Fi (even a compromised one) can reach the broker, whose ACL and the encrypted protocol limit what it can do, but not the API, ntfy or the services. `scripts/sim.sh probe` checks this:

```
From the iot network (a device on the house Wi-Fi):
  OK   mosquitto:1883  open          broker: nodes must reach it
  OK   api:8000        unknown host  web API / dashboard
  OK   ntfy:80         unknown host  alert server
  ...
segmentation OK
```

## Ports on the host

| Port | Service | Bound to | Change with |
|---|---|---|---|
| 8000 | dashboard + API | 127.0.0.1 only (no login yet) | `API_PORT=8001 scripts/sim.sh up` |
| 1883 | MQTT broker | 127.0.0.1 | `MQTT_BIND=0.0.0.0` to let a real ESP on the LAN connect |
| 8080 | ntfy (alerts) | all interfaces, so a phone on the same network can reach it | |

## Settings

Environment variables read by `compose.yml` (set them before `scripts/sim.sh` or `docker compose`):

| Variable | Default | Meaning |
|---|---|---|
| `EXIT_DELAY`, `ENTRY_DELAY` | 30 (5 and 10 with `sim.sh up`) | Seconds to leave after arming / to disarm after entering |
| `ALARM_SIM` | 0 (1 with `sim.sh up`) | Show the simulator panel on the dashboard |
| `API_PORT` | 8000 | Host port for the dashboard |
| `MQTT_BIND` | 127.0.0.1 | Host address the broker listens on |
| `CAMERA_SOURCE` | `--fake` | Camera input: `--fake` (generated frames), `--images=/app/data/test-images`, or `--device=0` |
| `NTFY_BASE_URL` | set by `scripts/dev-ntfy.sh` | Address the phone uses for ntfy (attachment links) |

## Data and secrets

- `../../.secrets` is mounted **read-only** into every container (keys, passwords, codes). It's never in the image.
- The service containers run as **your** user ID (`HOST_UID`/`HOST_GID`, set by `scripts/sim.sh`), so they can read `.secrets/` (mode 700) and write `data/`. Calling `docker compose` directly on Linux? Export them first: `export HOST_UID=$(id -u) HOST_GID=$(id -g)`.
- `../../data` is mounted read-write: `events.jsonl` (the log) and `snapshots/` (photos). It survives `sim.sh down`, so you can check it from the host with `verify-log`.
- ntfy accounts live in a Docker volume (`alarm_ntfy-auth`), kept across restarts. `docker compose … down -v` deletes them; rerun `FORCE=1 scripts/dev-ntfy.sh` after that.

## Using a real ESP

Start the box with the broker open to the LAN: `MQTT_BIND=0.0.0.0 scripts/sim.sh hub`. Then point the ESP at this machine's IP, port 1883, with its node key and password from `.secrets/dev.json`. The protocol encrypts everything, so an open broker port is expected; the ACL limits each node to its own topics.

## Webcam

Docker on macOS can't reach the Mac's webcam, so the camera container uses generated frames. To use the real webcam on a Mac, run the camera on the host instead (`.venv/bin/python -m alarm_camera run`) and leave the `camera` container stopped. On a Linux host, uncomment `devices` in `compose.yml` and set `CAMERA_SOURCE=--device=0`.

## Dev-only parts to remove on a real deployment

- The `attacker` user in `mosquitto/acl`, and the `sim/` lines (simulator remote control)
- `ALARM_SIM=1` (the simulator panel)
- The dev codes `1234` / `9999`: set real ones with `python -m alarm_core hash-code`

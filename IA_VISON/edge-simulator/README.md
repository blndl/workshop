# Sentinel-X Edge Simulator

Standalone C++17 simulation of the future ESP8266 firmware. It does not import or change the Presence webcam application: camera capture and inference remain browser-local. Docker runs separate DHT22, MQ-2 and PIR producer containers plus an Edge coordinator. Each producer publishes its sensor fragment on an internal MQTT topic; the coordinator merges readings and preserves the public `/sensors`, `/status`, `/alerts` and `/commands` device contract.

## Run with Docker (broker and simulator on one PC)

From this directory, in PowerShell (the defaults work without creating a `.env` file):

```powershell
Copy-Item .env.example .env
docker compose up --build
```

The bundled Mosquitto broker is exposed on ports 1883 (MQTT TCP) and 9001 (MQTT WebSockets for the browser dashboard). Docker Desktop should show `mosquitto`, `edge-simulator`, `sensor-dht22`, `sensor-mq2`, and `sensor-pir`. To demonstrate actual broker receipt and a command round trip, run `./scripts/test-mqtt.ps1`. It waits for sensor JSON and an alert event, verifies their contracts, sends `LED_RED`, and checks the coordinator output. Stop the stack with `docker compose down`.

## Run against a broker on another PC

Build the image, then point it at the reachable broker without changing C++:

```powershell
docker build -t sentinel-edge .
docker run --rm -e MQTT_HOST=192.168.10.10 -e MQTT_PORT=1883 sentinel-edge
```

For local native execution, set `MQTT_HOST=localhost` and use the broker's host port. The broker must allow the chosen client to connect; open its firewall port on the broker PC. On Docker Desktop, `host.docker.internal` is the usual hostname when a container needs to reach a broker running directly on the same Windows PC.

## Native build and tests

Requirements: C++17 compiler, CMake, pkg-config, `libmosquitto` development files, and `nlohmann-json` development package.

```sh
cmake -S . -B build -DBUILD_TESTING=ON
cmake --build build
ctest --test-dir build --output-on-failure
```

## Configuration

Copy `.env.example` to `.env` for Compose. `MQTT_HOST`, `MQTT_PORT`, `MQTT_CLIENT_ID`, optional username/password, TLS flag and CA certificate path are configurable. `SENSOR_INTERVAL_MS` defaults to 1000; `SCENARIO` defaults to `normal` and accepts `normal`, `gas_leak`, `overheat`, `intrusion`, `humidity_low`, `humidity_high`, or `combined_attack`. Alert limits default to gas `0.50`, temperature `35 C`, and relative humidity `40–60%`; configure them with `ALERT_GAS_THRESHOLD`, `ALERT_TEMPERATURE_THRESHOLD`, `ALERT_HUMIDITY_MIN`, and `ALERT_HUMIDITY_MAX`. Compose values come from `.env` or the shell environment; standalone `docker run` accepts `-e NAME=value` or `--env-file .env`.

The coordinator publishes `/alerts` only when the set of active alert conditions changes. It sends `event: triggered` on a new anomaly, `event: updated` when the active set changes, and `event: resolved` when all readings are back within limits. `alerts` remains an array of stable codes; `details` gives the severity, sensor, measured value, comparison, limit, and a ready-to-display French message. Motion is a warning; gas and overheat are critical; humidity out of range is a warning.

The simulator uses a persistent MQTT client session with automatic reconnect/backoff, retained online status, and an offline Last Will. Wi-Fi is represented as available because this process has no physical radio. OLED, buzzer and LED implementations are console adapters, isolated behind interfaces/classes for later GPIO/I2C replacements.

See [`../docs/mqtt.md`](../docs/mqtt.md) for the topic and payload contract.

## Visual dashboard

Start the Docker stack from this directory with `docker compose up --build`. From the project root, run `npm run dev` and open the Vite URL. Select **Capteurs MQTT**, keep the broker host as `localhost` on the same PC, leave port `9001`, and press **Connecter**. The browser dashboard uses the Mosquitto WebSocket listener; TCP port `1883` remains available to server-side MQTT clients. The device field defaults to `ESP8266-001` and must match `MQTT_CLIENT_ID`.

The dashboard displays live sensor measurements and short trends, marks the current alert thresholds (`gas >= 0.50`, `temperature >= 35 C`, `motion = true`), prints received JSON messages, and can publish remote buzzer/LED commands. When opening the web app from another PC, set the broker host to the reachable IP or hostname of the broker PC; the firewall must allow port `9001`.

## As a module of the alarm system (`alarm-node`)

`alarm-node` runs this simulator's DHT22 and MQ-2 sensors and scenarios as the alarm's **`env-1`** module. It speaks the alarm's encrypted protocol ([protocol/spec.md](../../protocol/spec.md), C++ library in [protocol/cpp](../../protocol/cpp)) instead of the plain JSON topics, so the core treats it like any other module: safety alarms, buzzer and LED commands, dashboard, Grafana, phone alerts.

From the repo root:

```bash
ENV_NODE=cpp scripts/sim.sh up                          # env-1 from C++ instead of Python
ENV_NODE=cpp ENV_SCENARIO=gas_leak scripts/sim.sh up    # or overheat, combined_attack, humidity_low/high, normal
docker compose -f infra/docker/compose.yml --profile sim-cpp logs -f env-1-cpp
```

| Reading | Sent as | Note |
|---|---|---|
| MQ-2 gas (0–1) | `gas` in ppm | × 800, so this simulator's 0.50 alert level is env-1's 400 ppm limit |
| DHT22 temperature | `temp` (°C) | env-1's safety limit is 57 °C: `overheat` crosses it after about 40 s |
| DHT22 humidity | `hum` (%) | Telemetry only |
| (enclosure) | `lid` | Always closed for now |

Thresholds live in the core's [`config/modules.yaml`](../../config/modules.yaml), not here: the module only reports readings. The PIR is not sent, because env-1 has no motion sensor; door-1 does.

`alarm-node` doesn't answer the dashboard's simulator panel (that's the Python simulator's dev-only channel): the scenario drives it.

It's built by `Dockerfile.alarm` (context: the repo root, since it needs `protocol/`). `cmake` builds it next to `sentinel-edge` when `../../protocol/cpp` exists, and skips it otherwise, so this folder still builds on its own.

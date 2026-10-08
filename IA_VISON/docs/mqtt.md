# Sentinel-X MQTT Contract

## Topics

The default device identifier is `ESP8266-001`. Topics are rooted at `sentinel/edge/{device_id}`:

| Topic suffix | Direction | QoS | Retained | Purpose |
| --- | --- | --- | --- | --- |
| `sensors` | device to server | 1 | no | Periodic DHT22, MQ-2 and PIR readings |
| `status` | device to server | 1 | online state only | Connectivity; Last Will reports offline |
| `alerts` | device to server | 1 | yes, latest state | Alert state transitions |
| `commands` | server to device | 1 | no | Buzzer and LED commands |

In the Docker simulator, DHT22, MQ-2, and PIR each run in their own producer container and publish fragments to `sentinel/internal/{device_id}/dht22`, `/mq2`, and `/pir`. The `edge-simulator` coordinator subscribes to those private topics, merges current values, and alone publishes the stable public sensor/status/alert topics listed above. Server consumers need not subscribe to internal topics or change their contract.

The client ID and each complete topic can be overridden with `MQTT_CLIENT_ID`, `MQTT_SENSORS_TOPIC`, `MQTT_STATUS_TOPIC`, `MQTT_ALERTS_TOPIC`, and `MQTT_COMMANDS_TOPIC`. The default interval is one second (`SENSOR_INTERVAL_MS=1000`).

## Sensor payload

The JSON object and field names are stable; `temperature`, `humidity`, and `gas` are JSON numbers, `motion` is a boolean, and `timestamp` is UTC ISO-8601:

```json
{
  "device_id": "ESP8266-001",
  "timestamp": "2026-10-07T10:30:00Z",
  "temperature": 24.7,
  "humidity": 51.2,
  "gas": 0.18,
  "motion": false
}
```

`gas` is a normalized simulation value from 0.0 to 1.0, not a calibrated ppm measurement. Scenarios move sensor values smoothly toward their targets.

## Status and alerts

Status JSON contains `device_id`, `status` (`online` or `offline`), `wifi`, `mqtt`, and `timestamp`. An online status is published on connection and retained; the MQTT Last Will publishes retained `offline` if the process or connection disappears. `wifi` is true in the simulator to represent a reachable host network, not a real ESP8266 radio.

Alert JSON contains `device_id`, `event` (`triggered`, `updated`, or `resolved`), `active`, `alerts` (an array of stable condition codes), `details`, and `timestamp`. It is published only when the active condition set changes, never once per ordinary sensor sample. The latest event is retained so a newly connected dashboard immediately learns the current alert state. `details` entries contain `code`, `sensor`, `severity`, `message`, `value`, `condition`, and `threshold`. Gas at or above `ALERT_GAS_THRESHOLD` (default `0.50`) and temperature at or above `ALERT_TEMPERATURE_THRESHOLD` (default `35 C`) are critical. Humidity below `ALERT_HUMIDITY_MIN` (default `40%`) or above `ALERT_HUMIDITY_MAX` (default `60%`) and PIR motion are warnings. An empty `alerts` array with `event: resolved` clears the dashboard after readings return to normal.

Example humidity alert:

```json
{
  "device_id": "ESP8266-001",
  "event": "triggered",
  "active": true,
  "alerts": ["humidity_high"],
  "details": [{
    "code": "humidity_high",
    "sensor": "DHT22",
    "severity": "warning",
    "message": "Humidité trop élevée : 68.5 % (maximum 60.0 %).",
    "value": 68.5,
    "condition": ">",
    "threshold": 60.0
  }],
  "timestamp": "2026-10-07T10:30:00Z"
}
```

## Commands

Publish a JSON object to the device `commands` topic:

```json
{"command":"BUZZER_ON","duration":5000}
```

Supported commands: `BUZZER_ON` (optional duration in ms; zero/omitted means until turned off), `BUZZER_OFF`, `LED_RED`, `LED_GREEN`, `LED_OFF`, and `RESET_ALERT` (turns the buzzer off). Command effects are printed by the console actuator adapters.

## Connection configuration

Set `MQTT_HOST` and `MQTT_PORT` via environment variables; no broker address is compiled in. TLS is opt-in with `MQTT_TLS=true`; set `MQTT_CA_CERT` to a CA bundle path where needed. Username/password are optional. The container's `localhost` is itself, so use the Compose service name `mosquitto` for the bundled broker, `host.docker.internal` for a Windows host broker, or the broker PC's reachable LAN address for a two-PC setup. The Compose broker exposes MQTT/TCP on `1883` and MQTT over WebSockets on `9001` for the browser dashboard. When hosting the UI on a different PC, enter the broker PC address and allow port `9001` through its firewall.
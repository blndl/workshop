# Alarm protocol v1 (Wi-Fi)

How sensor nodes (ESP8266) and the hub (Raspberry Pi) talk to each other.
This document is the contract: the firmware, the simulator and `alarm-core`
must all follow it. The Python reference implementation is in
[`python/`](python/), and [`test-vectors.json`](test-vectors.json) holds exact
byte-level examples for checking other implementations.

## 1. Overview

```
 ┌──────────┐    Wi-Fi (isolated IoT SSID)    ┌───────────────── Pi ─────────────────┐
 │  node    │  MQTT/TCP 1883                  │  Mosquitto broker ──▶ alarm-core     │
 │ (ESP8266)│ ───────────────────────────────▶│  (auth + ACL)         (decrypt,      │
 └──────────┘   alarm/v1/<node>/up            │                        verify, FSM)  │
              ◀─────────────────────────────  │                                      │
                alarm/v1/<node>/down          └──────────────────────────────────────┘
```

- **Transport:** MQTT 3.1.1 over plain TCP, to a Mosquitto broker on the Pi.
- **Security** comes from the messages themselves (section 4), not from the
  transport. Every message after the handshake is encrypted and
  authenticated with ChaCha20-Poly1305. Anyone on the Wi-Fi network, or
  anyone who controls the broker, can see that messages are flowing, but
  can't read, forge, alter or replay them.
- **Liveness:** each node sends a heartbeat every second. If the hub doesn't
  receive a valid one for 3 seconds, it raises `LINK_LOST` (section 7). This
  is the defence against jamming and deauthentication, which can't be
  prevented, only detected.

### Why these choices

| Choice | Reason |
|---|---|
| MQTT | IoT standard, broker gives per-node auth and ACLs, adding nodes is trivial, the simulator just connects to it |
| Security in the message, not TLS | TLS on an ESP8266 uses most of its RAM and takes seconds to handshake. Securing the message itself also protects against a compromised broker. |
| ChaCha20-Poly1305 | Fast in software on chips without AES hardware; encryption and authentication in one step; available on both sides ([rweather/Crypto](https://github.com/rweather/arduinolibs) on the ESP, `cryptography` in Python) |
| A new key for every session | Nonces can never repeat, and the ESP doesn't need to save a counter to flash |
| Text frames | Readable with `mosquitto_sub`, easy to build with `snprintf` |
| QoS 0 on one topic per direction | One TCP connection keeps messages in order, so a strictly increasing counter works. A lost heartbeat is corrected by the next one 1 s later. |

## 2. Identities and keys

- **Node ID** (`node`): 1–16 characters from `[a-z0-9-]`, e.g. `door-1`.
- **Master key** `K`: 32 random bytes, different for each node, shared by
  that node and the hub. Generate it with `openssl rand -hex 32`. It is
  compiled into the firmware from `firmware/secrets.h` (never committed) and
  given to the hub as a Docker secret.
- **Broker credentials:** a username and password for each node (the
  username is the node ID). These are only a first barrier. MQTT runs over
  plain TCP, so anyone who can sniff the Wi-Fi sees these passwords when a
  client logs in. The protocol must stay secure when they leak, and is
  designed to.

## 3. MQTT transport

| Topic | Direction | Who may publish |
|---|---|---|
| `alarm/v1/<node>/up` | node → hub | only `<node>` |
| `alarm/v1/<node>/down` | hub → node | only the hub |
| `alarm/v1/<node>/status` | broker → hub | the broker, as the node's Last Will |

- QoS 0, not retained, for `up` and `down`.
- The node connects with clean session, a keepalive of 5 s, and a Last
  Will of `offline` on `status`. After connecting it publishes `online`
  (retained) to `status`. **`status` is only a hint:** it is not
  authenticated, so it can be faked. The heartbeat watchdog is what counts.
- Broker ACL (Mosquitto `acl_file`):
  ```
  user hub
  topic readwrite alarm/v1/#

  pattern write alarm/v1/%u/up
  pattern write alarm/v1/%u/status
  pattern read  alarm/v1/%u/down
  ```
- `allow_anonymous false`. The broker listens only on the IoT interface,
  and the firewall accepts port 1883 only from the IoT subnet.

## 4. Message format

Each MQTT payload is one ASCII string with fields separated by `|` and no
trailing newline. The maximum payload size is **240 bytes**, which fits the
default 256-byte buffer of the ESP8266 MQTT library. Longer payloads are
dropped.

There are two kinds of message:

### 4.1 Signed messages (handshake only): `HELLO`, `WELCOME`

```
v1|<type>|-|0|<body>|<mac>
```

- `body` is a field list (section 4.3), **in plain text**.
- `mac` = the first 16 bytes of `HMAC-SHA256(K_hello, mac_input)`, written
  as 32 lowercase hex characters.
- `mac_input` = `<node>|v1|<type>|-|0|<body>`. The node ID comes from the
  topic and is included so that a message can't be moved to another node's
  topic.
- `K_hello` = `HKDF-SHA256(ikm=K, salt="", info="alarm/v1/hello", length=32)`.

### 4.2 Encrypted messages: `HB`, `EVT`, `CMD`, `ACK`

```
v1|<type>|<sid>|<ctr>|<sealed>
```

- `sid`: session ID, 8 lowercase hex characters (section 5).
- `ctr`: message counter in decimal, from 1 to 2³²−1, with no leading zeros.
- `sealed` = `base64url_nopad( ChaCha20-Poly1305(key, nonce, plaintext, aad) )`,
  which is the ciphertext followed by the 16-byte tag.
  - `key`: `K_up` or `K_down`, depending on direction (section 5).
  - `nonce` (12 bytes) = 4 zero bytes followed by `ctr` as an 8-byte
    big-endian number.
  - `aad` = `<node>|v1|<type>|<sid>|<ctr>` as ASCII.
  - `plaintext` = a field list (section 4.3).

The header is readable by anyone but is protected by the tag: changing
the type, the session ID, the counter or the node makes decryption fail.

### 4.3 Field lists

`key=value` pairs separated by `,`. A list may be empty.

- key: `[a-z][a-z0-9_]{0,15}`
- value: `[A-Za-z0-9._-]{1,48}` (base64url values are allowed)
- Keys must not repeat. Keys a receiver doesn't recognise are ignored, so
  fields can be added later without changing the version.

## 5. Session handshake

A session gives both sides fresh keys. It is set up every time the node
boots or reconnects to MQTT.

```
 node                                              hub
  │  HELLO  fw=0.1.0,nn=<16 random bytes, b64url>   │
  │ ───────────────────────────────────────────────▶│ check mac, rate limit
  │                                                 │ pn = 16 random bytes
  │  WELCOME nn=<echo>,pn=<b64url>                  │ store as *pending* session
  │ ◀───────────────────────────────────────────────│
  │ check mac, check nn is the one just sent        │
  │ derive keys                                     │ derive keys
  │  HB (ctr=1, sealed with K_up)                   │
  │ ───────────────────────────────────────────────▶│ decrypts with pending keys
  │                                                 │ → pending becomes current
```

Key derivation (both sides):

```
salt  = nn || pn                       (32 bytes)
K_up   = HKDF-SHA256(K, salt, info="alarm/v1/up|<node>",   32)
K_down = HKDF-SHA256(K, salt, info="alarm/v1/down|<node>", 32)
sid    = hex(pn[0:4])
```

Rules:

1. **Node:** generate `nn` with the hardware random number generator.
   Resend `HELLO` every 2 s, with the same `nn`, until a valid `WELCOME`
   arrives. Ignore any `WELCOME` whose `nn` doesn't match. Don't send
   encrypted messages until the session exists.
2. **Hub:** verify the mac first, then accept at most one valid `HELLO`
   per node per second and drop the rest. (Checking the mac first means
   forged `HELLO`s can't use up the real node's allowance.) A valid `HELLO`
   whose `nn` matches the pending session gets **the same `WELCOME` again**,
   because the node is only retrying. Any other valid `HELLO` creates a new
   *pending* session, replacing any previous pending one, but **leaves the
   current session running**.
3. **Hub:** the pending session becomes current only when the first valid
   encrypted message arrives under its keys. Only then are the old session's
   keys deleted.
4. Counters start at 1 in each direction of each session. The sender
   increases its counter by one for every message.
5. When a counter would go past 2³²−1, the node must start a new session.
   At one message per second that takes 136 years, so this is only a
   formal rule.

**Why rule 3:** an attacker who replays an old `HELLO` gets a `WELCOME`
back, but can't derive the keys without `K`. The pending session never
completes and the real session keeps working. Replaying a `HELLO` doesn't
cause a denial of service.

## 6. Message types

| Type | Dir | Kind | Fields | Meaning |
|---|---|---|---|---|
| `HELLO` | up | signed | `fw`, `nn` | Start a session |
| `WELCOME` | down | signed | `nn`, `pn` | Accept a session |
| `HB` | up | sealed | full sensor snapshot, `up`, `rssi` | Heartbeat, every 1 s |
| `EVT` | up | sealed | the sensors that changed | Sent immediately when a sensor changes |
| `CMD` | down | sealed | `id`, then actions | Command to the node |
| `ACK` | up | sealed | `id`, `ok` (`1`/`0`), optional `err` | Reply to a `CMD` |

### Sensor fields (`HB`, `EVT`)

| Key | Values | Meaning |
|---|---|---|
| `door` | `0` closed / `1` open | Reed switch |
| `pir` | `0` / `1` motion | PIR sensor |
| `lid` | `0` closed / `1` open | Enclosure tamper switch |
| `up` | seconds since boot | Uptime; a sudden drop means a reboot |
| `rssi` | dBm, e.g. `-61` | Wi-Fi signal strength; a sudden fall can indicate jamming |

A node only sends the sensors it actually has. The heartbeat always
carries the full current state, so if an `EVT` is lost the hub catches up
within a second.

### Commands (`CMD`)

`id` is a decimal number chosen by the hub and echoed back in the `ACK`.

| Key | Values | Meaning |
|---|---|---|
| `buzzer` | `0` / `1` | Local siren or buzzer |
| `led` | `off`, `armed`, `alarm` | Status LED pattern |

## 7. What the receiver does

The hub runs these checks on every `up` message, in this order. The node
runs the same checks on `down` messages.

```
size ≤ 240 and valid ASCII?           no → drop, count  malformed
split into 5 or 6 fields, version v1? no → drop, count  malformed
type known and allowed this way?      no → drop, count  malformed
signed message:  mac valid?           no → drop, LOG    auth_fail   (security event)
sealed message:  sid = current or
                 pending session?     no → drop, count  unknown_session
                 tag valid?           no → drop, LOG    auth_fail   (security event)
                 ctr > last ctr?      no → drop, LOG    replay      (security event)
accept: update last ctr, reset watchdog, pass fields to the state machine
```

- Comparisons of the mac and tag must take constant time
  (`hmac.compare_digest`).
- `last ctr` is updated only **after** the tag has been verified.
- Security events go to the hash-chained audit log, with the node, the
  type and a hash of the payload.
- `unknown_session` is normal for a moment after the hub restarts. The
  node handles it by starting a new session (section 8).

### Watchdog

- If the hub receives no valid encrypted message from a node for **3 s**
  (the node sends `HB` every second), it emits `LINK_LOST(node)`. The
  watchdog starts after the node's first session.
  - **Armed:** `LINK_LOST` triggers the alarm (*fail-secure*).
  - **Disarmed:** it creates a warning only.
- Any valid message clears it and emits `LINK_RESTORED(node)`.
- A `status=offline` message alone doesn't trigger `LINK_LOST`; it is only
  logged.

## 8. Recovery

| Situation | What happens |
|---|---|
| Node reboots | It sends a new `HELLO`. Because of rule 3, the hub switches session once the first `HB` arrives. |
| Wi-Fi or MQTT drops | The node reconnects with backoff (1, 2, 4… up to 30 s) and starts a new session. |
| Hub restarts (sessions lost) | The hub drops the node's messages as `unknown_session`. The node notices through the downlink keepalive (below) and starts a new session. |
| No `WELCOME` arrives | The node keeps resending `HELLO` every 2 s (rule 1). |

**Downlink keepalive:** the hub sends `CMD id=0` (no action) every 5 s to
each node with a current session, and the node answers with an `ACK` as
usual. If a node gets no valid `down` message for 10 s, it drops its
session and sends a new `HELLO`. This way, a node recovers from a hub
restart within about 10 s.

## 9. Security properties and limits

| Threat | Covered? | How |
|---|---|---|
| Eavesdropping on sensor state | ✅ | ChaCha20 encryption |
| Faking or altering messages | ✅ | Poly1305 tag, HMAC on the handshake |
| Replay within a session | ✅ | Strictly increasing counter |
| Replay across sessions | ✅ | Fresh `pn` from the hub gives fresh keys |
| Replayed `HELLO` causing DoS | ✅ | Pending/current sessions (rule 3) and rate limit |
| Moving a message to another node's topic | ✅ | Node ID in the AAD / mac input |
| Compromised broker | ✅ partly | It can drop or delay messages (the watchdog catches that), but it can't read or forge them |
| Jamming / deauthentication | ⚠️ detected only | Watchdog → `LINK_LOST` → alarm when armed. `rssi` trend is evidence. |
| Traffic analysis | ⚠️ | Message sizes and timing leak a little; `EVT` reveals *that* something changed. One option is padding plaintexts to a fixed length. |
| Stolen node (key extracted from flash) | ❌ | One key per node limits the damage: revoke that node's key and its broker account. ESP8266 has no secure key storage. |
| Firmware version in `HELLO` | ⚠️ | Readable in plain text; minor information leak, accepted |

## 10. Example

A complete exchange, taken from `test-vectors.json` (master key
`000102…1f`, `nn` = bytes 0–15, `pn` = bytes 16–31):

```
up    v1|HELLO|-|0|fw=0.1.0,nn=AAECAwQFBgcICQoLDA0ODw|1b2b30b8410c6d8001217a3c8825405d
down  v1|WELCOME|-|0|nn=AAECAwQFBgcICQoLDA0ODw,pn=EBESExQVFhcYGRobHB0eHw|3818375753785fc7bcdd54de92407b58
up    v1|HB|10111213|1|oALahjO4zeyg3Rvod23hpqL44EINSGiNBYCP7ypP0xRAiP_Ai2_q2apyL1x5hHpisQ
up    v1|EVT|10111213|2|Q5IxZnYtHsNjuOGWGeGTm7SqIVP4
down  v1|CMD|10111213|1|rb45mHg8evKYN5rm6mfoLbx1VH6ymhDBNftoQ_g
up    v1|ACK|10111213|3|xQZeJPtt7AWQISP_kIex_gw_JIf6GGh0WQ
```

The heartbeat decrypts to `door=0,pir=0,lid=0,up=12,rssi=-61`, but on the
network it's opaque. The session ID `10111213` is the first 4 bytes of `pn`.
The firmware's crypto code is correct once it produces exactly these
strings from the same inputs.

## 11. Versioning

- Adding fields or commands doesn't need a new version: receivers ignore
  unknown keys.
- Any change to the framing, the cryptography or the handshake needs `v2`.
  A hub may support both versions during a migration.

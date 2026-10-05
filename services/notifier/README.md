# notifier

Turns alarm-core events into phone alerts through a self-hosted [ntfy](https://ntfy.sh) server, attaching the camera's photo when there is one.

```
alarm_notifier/
  rules.py     which events alert, priority, throttling (pure logic)
  ntfy.py      HTTP backend (photo upload, RFC 2047 for non-ASCII headers)
  service.py   follows alarm/events, waits for photos, retries delivery
```

## Alerts

| Event | Priority | Photo |
|---|---|---|
| Alarm triggered | 5 urgent | First alarm photo (waits up to 2.5 s for it) |
| Duress code used | 5 urgent | Duress burst photo |
| Event log tampered | 5 urgent | |
| Security warning (forged/replayed message) | 4 high | |
| Sensor offline (link lost) | 4 high | |
| Enclosure opened while disarmed | 4 high | |
| Code lockout | 4 high | |
| Camera error | 4 high | |
| Arming refused | 3 default | |
| Arming / disarmed | 2 low | |

Non-urgent alerts repeat at most once a minute per source; the next one says how many were suppressed ("+29 similar in the last minute"). Urgent alerts are never throttled.

**Delivery:** a failed send is retried after 1, 2, 4… up to 60 s, for up to an hour. Errors that retrying can't fix (bad token, topic not allowed) are logged and dropped. The queue is in memory, so alerts pending during a restart are lost (a disk spool would be the next improvement).

## Setup

```bash
scripts/dev-ntfy.sh          # starts ntfy, creates accounts, prints phone instructions
```

This creates two ntfy accounts, with everything else denied (`auth-default-access: deny-all`):

| Account | Access | Used by |
|---|---|---|
| `notifier` | write-only token for topic `alarm` | this service |
| `phone` | read-only login for topic `alarm` | the ntfy app on your phone |

**On your phone:** install the ntfy app, add a subscription to topic `alarm` on "another server" `http://<your computer's IP>:8080` (the script prints it), and log in as `phone`. The phone must be on the same Wi-Fi; on the Pi, use the VPN to receive alerts away from home. You can also open that address in a browser.

Test it:

```bash
.venv/bin/python -m alarm_notifier send "hello from the alarm"
.venv/bin/python -m alarm_notifier send "with a photo" --image data/snapshots/<day>/<file>.jpg --priority 5
```

**Quick test without self-hosting:** use a long random topic on the public server (anyone who guesses it can read it, so test messages only):

```bash
.venv/bin/python -m alarm_notifier --ntfy-url https://ntfy.sh --topic alarm-test-$RANDOM$RANDOM --no-auth send "hello"
```

## Running it

```bash
.venv/bin/python -m alarm_notifier run      # needs the broker, ntfy, and alarm-core running
```

## Privacy and security notes (for the report)

- **Photos stay on your server.** On iPhone, ntfy.sh only relays a wake-up signal (`upstream-base-url`); the message and photo are fetched from your server.
- **Attachment links are capability URLs.** Anyone who has the link (`/file/<random id>.jpg`) can download the photo without logging in, until it expires after 3 h (`attachment-expiry-duration`). Keep ntfy reachable only on your network or VPN, never exposed directly to the internet.
- **Plain HTTP in dev.** On the Pi, put ntfy behind HTTPS or reach it only through WireGuard.
- **Duress alerts go to the phone only.** Every local display (CLI, future dashboard) hides them.

## Tests

```bash
.venv/bin/pytest services/notifier
```

Covers rules and throttling, attaching photos (and refusing paths outside the snapshot folder), retries, the exact HTTP requests sent to a fake ntfy server, and an end-to-end intrusion plus duress code ending with photos on the "phone".

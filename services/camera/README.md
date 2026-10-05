# camera

Takes webcam snapshots when the alarm needs them, stores them with a retention limit, and announces each one so alarm-core records its SHA-256 in the tamper-evident log.

```
alarm_camera/
  policy.py    when to capture (pure logic)
  sources.py   webcam (OpenCV), folder of test images, fake frames
  store.py     data/snapshots/<day>/<time>_<reason>.jpg, retention pruning
  service.py   MQTT wiring
```

## When it captures

| Situation | Pictures |
|---|---|
| **Disarmed** | **None. The webcam is closed** (privacy: the people living there aren't filmed) |
| Arming | Camera opens and warms up; nothing captured yet |
| Sensor goes to 1 while armed | 1 picture |
| Entry delay starts | Burst of 3 (0, 0.7, 1.4 s) |
| Alarm triggered | Burst of 3, then 1 every 5 s for 60 s |
| Duress code used | Burst of 3, silently, even though the system then shows as disarmed |

Snapshots older than **30 days** are deleted (CNIL guidance for video surveillance; change with `--retention-days`).

## Evidence integrity

For each picture the camera publishes `{"type": "snapshot", "path", "sha256", "reason"}` on `alarm/snapshots`. alarm-core writes it into its hash-chained log, so:

```bash
.venv/bin/python -m alarm_core verify-log --snapshots   # chain + every logged image
```

reports any picture that was deleted or edited. If the camera fails (unplugged, permission denied), a `camera_error` event is logged instead.

## Running it

```bash
.venv/bin/pip install -e 'services/camera[webcam]'

.venv/bin/python -m alarm_camera snap                 # test the webcam: writes snapshot.jpg
.venv/bin/python -m alarm_camera run                  # the service (Mac webcam or USB webcam on the Pi)
.venv/bin/python -m alarm_camera --fake run           # no camera: generated frames
.venv/bin/python -m alarm_camera --images DIR run     # cycle through test .jpg files
```

Source options (`--device N`, `--images DIR`, `--fake`) go **before** the command.

**macOS:** the first time you use the webcam, macOS asks to allow camera access for your terminal (or VS Code). If you said no, enable it in System Settings → Privacy & Security → Camera, then restart the terminal.

**On the Pi:** a USB webcam works as-is through OpenCV (V4L2). The ribbon-cable Pi Camera module needs a `picamera2` source instead, which isn't written yet.

## Tests

```bash
.venv/bin/pytest services/camera
```

`test_camera_e2e.py` runs the simulated node, alarm-core and the camera together: arm, open the door, let the entry delay run out, then check that every snapshot's file matches the hash in the log and that the camera closes after disarming.

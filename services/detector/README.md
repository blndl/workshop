# detector

Person detection on the camera's snapshots, with **YOLOv8n** (COCO, 80 classes) through ONNX Runtime on the CPU. It runs on the core, not in a browser, so it works with no dashboard open. It reports people, plus the usual false-alarm culprits (cat, dog, bird).

```
alarm_detector/
  yolo.py      letterbox → ONNX → decode + NMS → boxes normalised to the image (0-1)
  service.py   reads 'snapshot' events, publishes results
  __main__.py  run / detect / evaluate
```

## Model

The model is **not in git** (12.8 MB). Fetch it once:

```bash
scripts/get-model.sh        # → models/yolov8n.onnx (git-ignored); sim.sh runs it automatically
```

It copies the one that ships with the vision work (`IA_VISON/public/models/`, merged into `main`), otherwise downloads it from the Hugging Face mirror it came from (`salim4n/yolov8n-detect-onnx`). **Licence:** Ultralytics YOLO is AGPL-3.0. Fine for a school project, but check before any redistribution.

Without a model the service still runs and reports `ready: false`. Motion then always counts, after the vision timeout (fail-secure).

## What it does with each photo

| In | Out |
|---|---|
| `alarm/events` → `snapshot` (path, reason) | `alarm/detections`: `{path, reason, person, confidence, objects: {"person": 2, "cat": 1}, boxes: [{label, confidence, x, y, w, h}], latency_ms}` |
| every 10 s | `alarm/detector/status` (retained): `ready`, `model`, `processed`, `persons`, `errors`, `last_latency_ms` |

alarm-core writes each result into the tamper-evident log (`detection` events), so the log also records **what the AI saw**. It uses the results of the camera's **verify burst** to confirm or dismiss motion; see "Vision" in [alarm-core's README](../alarm-core/README.md).

It only reads photos inside `data/snapshots/` (no path tricks) and mounts `data/` read-only.

## Speed

About **200 ms per photo** on a laptop CPU when warm (650–850 ms in Docker on a Mac, measured). A burst of 3 photos is checked within the 8 s vision timeout. On a Raspberry Pi 4, expect 1–2 s per photo, still inside the timeout.

## Try it and measure it

```bash
.venv/bin/python -m alarm_detector detect photo.jpg
.venv/bin/python -m alarm_detector evaluate my-photos/ -v    # my-photos/person/*.jpg, my-photos/no_person/*.jpg
```

`evaluate` prints the numbers for the report: people found or missed, **false alarms without and with the person check**, and latency. Build the dataset from your own photos: yourself, a pet, an empty room, lights switching on, a moving curtain. Don't commit photos of people (GDPR).

To feed the live system with photos instead of a webcam: put them in `data/test-images/`, then
`CAMERA_SOURCE=--images=/app/data/test-images scripts/sim.sh up`. The camera cycles through them.

## Tests

```bash
.venv/bin/pytest services/detector
```

Decoding and NMS run on synthetic model outputs; the service runs with a fake detector; one test uses the real model if `models/` has it (skipped in CI).

"""alarm-detector: person detection on the camera's snapshots (YOLOv8n).

    python -m alarm_detector run                 # the service
    python -m alarm_detector detect photo.jpg    # try one image
    python -m alarm_detector evaluate DIR        # DIR/person/*.jpg and DIR/no_person/*.jpg
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEFAULT_MODEL = REPO / "models" / "yolov8n.onnx"
DEFAULT_SECRETS = REPO / ".secrets" / "dev.json"
DEFAULT_SNAPSHOTS = REPO / "data" / "snapshots"


def load_detector(args):
    from .yolo import Detector

    if not args.model.exists():
        print(f"[detector] no model at {args.model}: run scripts/get-model.sh")
        return None
    return Detector(str(args.model), args.threshold)


def cmd_detect(args) -> int:
    d = load_detector(args)
    if d is None:
        return 1
    boxes, ms = d.detect_jpeg(args.image.read_bytes())
    print(f"{args.image}: {len(boxes)} object(s), {ms:.0f} ms")
    for b in boxes:
        print(f"  {b.label:<8} {b.confidence:.2f}  x={b.x:.2f} y={b.y:.2f} w={b.w:.2f} h={b.h:.2f}")
    return 0


def cmd_evaluate(args) -> int:
    """Labelled photos -> how many false alarms the person check removes."""
    d = load_detector(args)
    if d is None:
        return 1
    rows = []
    for label in ("person", "no_person"):
        for f in sorted((args.dir / label).glob("*.jp*g")):
            boxes, ms = d.detect_jpeg(f.read_bytes())
            rows.append((label == "person", any(b.label == "person" for b in boxes), ms, f.name))
    if not rows:
        sys.exit(f"no photos: put them in {args.dir}/person/ and {args.dir}/no_person/")
    tp = sum(1 for truth, pred, *_ in rows if truth and pred)
    fn = sum(1 for truth, pred, *_ in rows if truth and not pred)
    fp = sum(1 for truth, pred, *_ in rows if not truth and pred)
    tn = sum(1 for truth, pred, *_ in rows if not truth and not pred)
    negatives = fp + tn
    print(f"photos: {len(rows)} ({tp + fn} with a person, {negatives} without)")
    print(f"people found:             {tp}/{tp + fn}" + (f"  (recall {tp / (tp + fn):.0%})" if tp + fn else ""))
    print(f"people missed:            {fn}   <- the alarm still proceeds after the timeout")
    if negatives:
        print(f"false alarms without AI:  {negatives}   (every motion would alarm)")
        print(f"false alarms with AI:     {fp}   ({1 - fp / negatives:.0%} removed)")
    print(f"latency: median {sorted(r[2] for r in rows)[len(rows) // 2]:.0f} ms")
    if args.verbose:
        for truth, pred, ms, name in rows:
            print(f"  {'OK ' if truth == pred else 'ERR'} {name:<30} truth={'person' if truth else 'none':<7} detected={pred}")
    return 0


def cmd_run(args) -> int:
    from alarm_protocol.transport import MqttTransport

    from .service import DetectorService

    if not args.secrets.exists():
        sys.exit(f"{args.secrets} not found. Run scripts/dev-secrets.sh first.")
    s = json.loads(args.secrets.read_text())
    if args.broker:
        host, _, port = args.broker.partition(":")
        port = int(port or 1883)
    else:
        b = s.get("broker", {})
        host, port = b.get("host", "127.0.0.1"), int(b.get("port", 1883))
    transport = MqttTransport(host, port, "detector", s["detector"]["password"], client_id="alarm-detector")
    service = DetectorService(load_detector(args), args.snapshots, transport, args.model.name)
    service.start()
    print(f"[detector] connected to {host}:{port}; model {args.model.name}; snapshots in {args.snapshots}")
    try:
        while True:
            service.tick(time.monotonic())
            time.sleep(0.05)
    except KeyboardInterrupt:
        return 0
    finally:
        transport.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="alarm-detector", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    p.add_argument("--threshold", type=float, default=0.4, help="minimum confidence (default 0.4)")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the service")
    r.add_argument("--secrets", type=Path, default=DEFAULT_SECRETS)
    r.add_argument("--broker", help="host[:port], overrides the secrets file")
    r.add_argument("--snapshots", type=Path, default=DEFAULT_SNAPSHOTS)
    d = sub.add_parser("detect", help="detect in one image")
    d.add_argument("image", type=Path)
    e = sub.add_parser("evaluate", help="false-alarm reduction on labelled photos")
    e.add_argument("dir", type=Path)
    e.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    return {"run": cmd_run, "detect": cmd_detect, "evaluate": cmd_evaluate}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())

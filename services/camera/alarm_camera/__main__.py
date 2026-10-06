"""alarm-camera: takes snapshots when the alarm needs them.

    python -m alarm_camera snap                 # one test picture from the webcam
    python -m alarm_camera run                  # the service, with the webcam
    python -m alarm_camera run --images DIR     # cycle through test .jpg files instead
    python -m alarm_camera run --fake           # generated frames, no camera needed
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from alarm_protocol.transport import MqttTransport

from .service import CameraService
from .sources import FakeSource, FolderSource, OpenCVSource
from .store import DEFAULT_RETENTION_DAYS, SnapshotStore

REPO = Path(__file__).resolve().parents[3]
DEFAULT_SECRETS = REPO / ".secrets" / "dev.json"
DEFAULT_DIR = REPO / "data" / "snapshots"


def broker(args, s: dict) -> tuple[str, int]:
    if args.broker:
        host, _, port = args.broker.partition(":")
        return host, int(port or 1883)
    b = s.get("broker", {})
    return b.get("host", "127.0.0.1"), int(b.get("port", 1883))


def make_source(args):
    if args.fake:
        return FakeSource()
    if args.images:
        return FolderSource(args.images)
    return OpenCVSource(args.device)


def cmd_snap(args) -> int:
    source = make_source(args)
    try:
        source.open()
        jpeg = source.latest_jpeg()
    except RuntimeError as e:
        sys.exit(f"error: {e}")
    finally:
        source.close()
    args.out.write_bytes(jpeg)
    print(f"wrote {args.out} ({len(jpeg) // 1024} KB)")
    return 0


def cmd_run(args) -> int:
    if not args.secrets.exists():
        sys.exit(f"{args.secrets} not found. Run scripts/dev-secrets.sh first.")
    s = json.loads(args.secrets.read_text())
    host, port = broker(args, s)
    transport = MqttTransport(host, port, "camera", s["camera"]["password"], client_id="alarm-camera")
    store = SnapshotStore(args.dir, args.retention_days)
    service = CameraService(make_source(args), store, transport)
    service.start()
    print(f"[camera] connected to {host}:{port}; snapshots in {args.dir}, kept {args.retention_days:g} days")
    print("[camera] closed until the system is armed (privacy)")
    try:
        while True:
            service.tick(time.monotonic())
            time.sleep(0.05)
    except KeyboardInterrupt:
        return 0
    finally:
        service.source.close()
        transport.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="alarm-camera", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--secrets", type=Path, default=DEFAULT_SECRETS)
    p.add_argument("--broker", help="host[:port], overrides the secrets file")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--device", type=int, default=0, help="webcam index (default 0)")
    src.add_argument("--images", type=Path, help="folder of .jpg test images")
    src.add_argument("--fake", action="store_true", help="generated frames")
    sub = p.add_subparsers(dest="cmd", required=True)

    snap = sub.add_parser("snap", help="take one picture and exit")
    snap.add_argument("--out", type=Path, default=Path("snapshot.jpg"))

    run = sub.add_parser("run", help="run the camera service")
    run.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    run.add_argument("--retention-days", type=float, default=DEFAULT_RETENTION_DAYS)

    args = p.parse_args(argv)
    return {"snap": cmd_snap, "run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())

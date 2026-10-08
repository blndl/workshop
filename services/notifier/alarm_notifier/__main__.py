"""alarm-notifier: phone alerts through ntfy.

    python -m alarm_notifier send "hello"                 # test message
    python -m alarm_notifier send "hi" --image snap.jpg --priority 5
    python -m alarm_notifier run                          # the service
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from alarm_protocol.transport import MqttTransport

from .ntfy import NtfyBackend, SendError
from .rules import Alert
from .service import NotifierService

REPO = Path(__file__).resolve().parents[3]
DEFAULT_SECRETS = REPO / ".secrets" / "dev.json"
DEFAULT_SNAPSHOTS = REPO / "data" / "snapshots"


def load(args) -> dict:
    if not args.secrets.exists():
        sys.exit(
            f"{args.secrets} not found. "
            "Run scripts/dev-secrets.sh and scripts/dev-ntfy.sh first."
        )
    return json.loads(args.secrets.read_text())


def backend(args, s: dict) -> NtfyBackend:
    n = s.get("ntfy", {})

    url = args.ntfy_url or n.get("url")
    topic = args.topic or n.get("topic")
    token = None if args.no_auth else (args.token or n.get("token"))

    if not url or not topic:
        sys.exit(
            "no ntfy server configured: run scripts/dev-ntfy.sh, "
            "or pass --ntfy-url and --topic"
        )

    return NtfyBackend(url, topic, token)


def cmd_send(args) -> int:
    b = backend(args, load(args))

    alert = Alert(
        args.title,
        args.message,
        args.priority,
        args.tags.split(",") if args.tags else [],
        image=args.image,
    )

    try:
        b.send(alert)
    except SendError as e:
        sys.exit(f"error: {e}")

    print(f"sent to {b.endpoint}")
    return 0


def cmd_run(args) -> int:
    s = load(args)

    if args.broker:
        host, _, port = args.broker.partition(":")
        port = int(port or 1883)
    else:
        br = s.get("broker", {})
        host = br.get("host", "127.0.0.1")
        port = int(br.get("port", 1883))

    transport = MqttTransport(
        host,
        port,
        "notifier",
        s["notifier"]["password"],
        client_id="alarm-notifier",
    )

    # Existing local ntfy backend
    b = backend(args, s)

    # iPhone notification through public ntfy.sh
    phone_backend = NtfyBackend(
        "https://ntfy.sh",
        "yassin-alarm-demo-2026",
    )

    # Send every alarm to both destinations
    service = NotifierService(
        b,
        transport,
        args.snapshots,
        extra_backends=[phone_backend],
    )

    service.start()

    print(
        f"[notifier] connected to {host}:{port}, "
        f"alerts go to {b.endpoint} and "
        f"https://ntfy.sh/yassin-alarm-demo-2026"
    )

    try:
        while True:
            service.tick(time.monotonic())
            time.sleep(0.1)
    except KeyboardInterrupt:
        return 0
    finally:
        transport.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="alarm-notifier",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    p.add_argument("--secrets", type=Path, default=DEFAULT_SECRETS)
    p.add_argument("--broker", help="host[:port], overrides the secrets file")
    p.add_argument("--ntfy-url", help="override the server, e.g. https://ntfy.sh")
    p.add_argument("--topic", help="override the topic")
    p.add_argument("--token", help="override the access token")
    p.add_argument(
        "--no-auth",
        action="store_true",
        help="send without a token (public ntfy.sh topic)",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("send", help="send one test alert")
    s.add_argument("message")
    s.add_argument("--title", default="Test")
    s.add_argument("--priority", type=int, default=3, choices=range(1, 6))
    s.add_argument("--tags", default="test_tube")
    s.add_argument("--image", type=Path)

    r = sub.add_parser("run", help="run the notifier service")
    r.add_argument(
        "--snapshots",
        type=Path,
        default=DEFAULT_SNAPSHOTS,
    )

    args = p.parse_args(argv)

    return {
        "send": cmd_send,
        "run": cmd_run,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
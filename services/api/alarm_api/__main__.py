"""alarm-api: the web API.

    python -m alarm_api                  # http://127.0.0.1:8000, docs at /docs
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import uvicorn

from alarm_protocol.transport import MqttTransport

from .app import create_app
from .bridge import Bridge

REPO = Path(__file__).resolve().parents[3]
DEFAULT_SECRETS = REPO / ".secrets" / "dev.json"
DEFAULT_WEB = REPO / "web" / "dist"


# Successful GETs that happen every few seconds (Prometheus scrapes, dashboard polling).
QUIET_PATHS = ("/metrics", "/api/state", "/api/events", "/api/sim", "/api/health", "/api/info")


class _QuietPolling(logging.Filter):
    """Drop routine 200 GETs from the access log; keep changes (POST) and every error."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 5:
            method, path, status = args[1], str(args[2]), args[4]
            if method == "GET" and status == 200 and path.split("?")[0] in QUIET_PATHS:
                return False
        return True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="alarm-api", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--secrets", type=Path, default=DEFAULT_SECRETS)
    p.add_argument("--broker", help="host[:port], overrides the secrets file")
    p.add_argument("--host", default="127.0.0.1", help="keep 127.0.0.1 until login (D2) exists")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--sim", action="store_true", default=os.environ.get("ALARM_SIM") == "1",
                   help="enable the simulator control panel (dev only; or ALARM_SIM=1)")
    p.add_argument("--web", type=Path, default=DEFAULT_WEB, help="built dashboard to serve (default web/dist)")
    args = p.parse_args(argv)

    if not args.secrets.exists():
        sys.exit(f"{args.secrets} not found. Run scripts/dev-secrets.sh first.")
    s = json.loads(args.secrets.read_text())
    if "api" not in s:
        sys.exit("no 'api' account in the secrets file: run scripts/dev-secrets.sh, then restart the broker")
    if args.broker:
        host, _, port = args.broker.partition(":")
        port = int(port or 1883)
    else:
        b = s.get("broker", {})
        host, port = b.get("host", "127.0.0.1"), int(b.get("port", 1883))

    transport = MqttTransport(host, port, "api", s["api"]["password"], client_id="alarm-api")
    store = None
    if os.environ.get("DATABASE_URL"):
        from .database import EventStore

        # Backfill from alarm-core's log so events from before the API started aren't missing.
        store = EventStore(os.environ["DATABASE_URL"], backfill_from=REPO / "data" / "events.jsonl")
    # GRAFANA_URL is the address the *browser* uses (the dashboard embeds it in its Metrics tab).
    bridge = Bridge(transport, sim=args.sim, store=store, history_from=REPO / "data" / "events.jsonl")
    app = create_app(bridge, args.web, os.environ.get("GRAFANA_URL") or None,
                     snapshots_dir=REPO / "data" / "snapshots")
    web = "dashboard at /" if (args.web / "index.html").exists() else "no dashboard build (cd web && npm run build)"
    print(f"[api] broker {host}:{port}; http://{args.host}:{args.port} ({web}, docs at /docs)" + (", SIM CONTROL ON" if args.sim else "") + (", events -> PostgreSQL" if store else ", no DATABASE_URL: events in memory only"))
    logging.getLogger("uvicorn.access").addFilter(_QuietPolling())
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())

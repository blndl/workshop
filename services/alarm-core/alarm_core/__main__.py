"""alarm-core: the alarm state machine on the Pi.

    python -m alarm_core run                 # the service (replaces `alarm_sim hub`)
    python -m alarm_core ctl arm 1234        # control it
    python -m alarm_core ctl disarm 1234
    python -m alarm_core ctl status
    python -m alarm_core watch               # follow events live
    python -m alarm_core verify-log          # check the event log's hash chain
    python -m alarm_core hash-code           # hash a new code for the config
"""

from __future__ import annotations

import argparse
import getpass
import json
import queue
import secrets as pysecrets
import sys
import time
from pathlib import Path

from alarm_protocol.transport import MqttTransport

from .codes import CodeChecker, hash_code
from .eventlog import EventLog, verify
from .machine import AlarmMachine, Timing
from .service import CONTROL_TOPIC, EVENTS_TOPIC, STATE_TOPIC, AlarmService

REPO = Path(__file__).resolve().parents[3]
DEFAULT_SECRETS = REPO / ".secrets" / "dev.json"
DEFAULT_LOG = REPO / "data" / "events.jsonl"


def load_secrets(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"{path} not found. Run scripts/dev-secrets.sh first.")
    return json.loads(path.read_text())


def broker(args, secrets: dict) -> tuple[str, int]:
    if args.broker:
        host, _, port = args.broker.partition(":")
        return host, int(port or 1883)
    b = secrets.get("broker", {})
    return b.get("host", "127.0.0.1"), int(b.get("port", 1883))


def cmd_run(args) -> int:
    s = load_secrets(args.secrets)
    host, port = broker(args, s)
    keys = {n: bytes.fromhex(v["key"]) for n, v in s["nodes"].items()}
    codes = CodeChecker(s["codes"]["user"], s["codes"]["duress"])
    timing = Timing(args.exit_delay, args.entry_delay, args.siren_max)
    machine = AlarmMachine(list(keys), codes, timing, now=time.monotonic())
    transport = MqttTransport(host, port, "hub", s["hub"]["password"], client_id="alarm-core")
    eventlog = EventLog(args.log, bytes.fromhex(s["log_key"]))
    check = eventlog.startup_check
    print(f"[alarm] event log {args.log}: {check.count} records, " + ("chain OK" if check.ok else f"{len(check.problems)} PROBLEM(S)"))
    service = AlarmService(keys, machine, transport, eventlog=eventlog)
    service.start()
    print(f"[alarm] connected to {host}:{port}, nodes: {', '.join(keys)}")
    print(f"[alarm] exit delay {timing.exit_delay:g}s, entry delay {timing.entry_delay:g}s, siren max {timing.siren_max:g}s")
    try:
        while True:
            service.tick(time.monotonic())
            time.sleep(0.05)
    except KeyboardInterrupt:
        return 0
    finally:
        transport.close()


def _ctl_client(args):
    s = load_secrets(args.secrets)
    host, port = broker(args, s)
    inbox: queue.SimpleQueue = queue.SimpleQueue()
    t = MqttTransport(host, port, "ctl", s["ctl"]["password"], client_id=f"ctl-{pysecrets.token_hex(3)}")
    connected = queue.SimpleQueue()
    t.subscribe(EVENTS_TOPIC, lambda _t, p: inbox.put(json.loads(p)))
    t.connect(on_connect=lambda: connected.put(True))
    try:
        connected.get(timeout=5)
    except queue.Empty:
        sys.exit(f"could not connect to {host}:{port}")
    time.sleep(0.2)  # let the subscription settle
    return t, inbox


def cmd_ctl(args) -> int:
    t, inbox = _ctl_client(args)
    req = pysecrets.token_hex(4)
    msg = {"action": args.action, "source": "cli", "req": req}
    if args.action in ("arm", "disarm"):
        msg["code"] = args.code or getpass.getpass("code: ")
    t.publish(CONTROL_TOPIC, json.dumps(msg))
    deadline = time.monotonic() + 2.0
    got = False
    while time.monotonic() < deadline:
        try:
            e = inbox.get(timeout=0.1)
        except queue.Empty:
            continue
        if e.get("req") != req or e["type"] == "duress":
            continue  # never show a duress event to whoever is holding the keypad
        if e["type"] == "control_done":
            break
        got = True
        if e["type"] == "status":
            e.pop("req"), e.pop("type")
            print(json.dumps(e, indent=2))
        elif e["type"] == "state":
            delay = f" in {e['delay']:g}s" if "delay" in e else ""
            print(f"{e['prev']} -> {e['state']}{delay}")
        else:
            print(e["type"], {k: v for k, v in e.items() if k not in ("ts", "type", "req")})
    else:
        t.close()
        print("no reply: is alarm-core running?")
        return 1
    t.close()
    if not got:
        print("ok (no change)")
    return 0


def cmd_watch(args) -> int:
    t, inbox = _ctl_client(args)
    print("watching alarm/events (ctrl-c to stop)")
    try:
        while True:
            try:
                e = inbox.get(timeout=0.5)
            except queue.Empty:
                continue
            ts = time.strftime("%H:%M:%S", time.localtime(e.pop("ts")))
            print(ts, e.pop("type"), json.dumps(e))
    except KeyboardInterrupt:
        return 0
    finally:
        t.close()


def cmd_verify_log(args) -> int:
    s = load_secrets(args.secrets)
    head = None
    if args.head:
        seq, _, mac = args.head.partition(":")
        head = (int(seq), mac)
    r = verify(args.log, bytes.fromhex(s["log_key"]), head)
    print(f"{args.log}: {r.count} records, head seq {r.head_seq} {r.head_mac[:16]}")
    if args.snapshots:
        checked = _check_snapshots(args.log, args.snapshots, r.problems)
        print(f"checked {checked} snapshot(s) against their logged sha256")
    if r.ok:
        print("OK: hash chain intact")
        return 0
    print(f"TAMPERED: {len(r.problems)} problem(s)")
    for problem in r.problems:
        print(f"  - {problem}")
    return 1


def _check_snapshots(log: Path, root: Path, problems: list[str]) -> int:
    import hashlib

    checked = 0
    for line in log.read_text().splitlines():
        try:
            e = json.loads(line)["event"]
        except (ValueError, KeyError):
            continue  # already reported by verify()
        if e.get("type") != "snapshot":
            continue
        checked += 1
        f = root / e["path"]
        if not f.exists():
            problems.append(f"snapshot {e['path']} (seq {e.get('seq')}): missing")
        elif hashlib.sha256(f.read_bytes()).hexdigest() != e["sha256"]:
            problems.append(f"snapshot {e['path']} (seq {e.get('seq')}): image modified")
    return checked


def cmd_hash_code(args) -> int:
    code = getpass.getpass("new code (4-8 digits): ")
    if code != getpass.getpass("again: "):
        sys.exit("codes differ")
    print(hash_code(code))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="alarm-core", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--secrets", type=Path, default=DEFAULT_SECRETS)
    p.add_argument("--broker", help="host[:port], overrides the secrets file")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run the alarm service")
    r.add_argument("--exit-delay", type=float, default=30.0)
    r.add_argument("--entry-delay", type=float, default=30.0)
    r.add_argument("--siren-max", type=float, default=180.0)
    r.add_argument("--log", type=Path, default=DEFAULT_LOG)

    c = sub.add_parser("ctl", help="send a control request")
    c.add_argument("action", choices=["arm", "disarm", "status"])
    c.add_argument("code", nargs="?", help="omit to be prompted")

    sub.add_parser("watch", help="print events as they happen")
    sub.add_parser("hash-code", help="hash a code for the secrets file")
    v = sub.add_parser("verify-log", help="check the event log's hash chain")
    v.add_argument("--log", type=Path, default=DEFAULT_LOG)
    v.add_argument("--head", help="SEQ:MAC from alarm/state, to also detect truncation")
    v.add_argument("--snapshots", type=Path, nargs="?", const=REPO / "data" / "snapshots",
                   help="also check each logged snapshot image (default dir: data/snapshots)")

    args = p.parse_args(argv)
    commands = {"run": cmd_run, "ctl": cmd_ctl, "watch": cmd_watch, "hash-code": cmd_hash_code, "verify-log": cmd_verify_log}
    return commands[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())

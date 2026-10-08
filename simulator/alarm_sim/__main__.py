"""alarm-sim: fake sensor nodes, attacks and a dev hub.

    python -m alarm_sim selftest                    # all scenarios, offline, fast
    python -m alarm_sim hub                         # dev hub on the MQTT broker
    python -m alarm_sim node                        # interactive node door-1
    python -m alarm_sim node --scenario scenarios/intrusion.yaml
"""

from __future__ import annotations

import argparse
import json
import queue
import shlex
import sys
import threading
import time
from pathlib import Path

from alarm_protocol.hub import status_topic

from . import scenario as scenario_mod
from .attacks import ATTACKS, Attacker
from .control import SimControl
from .devhub import DevHub
from alarm_protocol.modules import ModuleError, load as load_modules

from .node import SimNode
from alarm_protocol.transport import MemoryBus, MqttTransport

REPO = Path(__file__).resolve().parents[2]
DEFAULT_SECRETS = REPO / ".secrets" / "dev.json"
SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"
DEFAULT_MODULES = REPO / "config" / "modules.yaml"


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        self.t += dt


def load_secrets(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"{path} not found. Run scripts/dev-secrets.sh first.")
    return json.loads(path.read_text())


def node_keys(secrets: dict) -> dict[str, bytes]:
    return {n: bytes.fromhex(v["key"]) for n, v in secrets["nodes"].items()}


def broker(args, secrets: dict) -> tuple[str, int]:
    if args.broker:
        host, _, port = args.broker.partition(":")
        return host, int(port or 1883)
    b = secrets.get("broker", {})
    return b.get("host", "127.0.0.1"), int(b.get("port", 1883))


# --- selftest -----------------------------------------------------------------


def cmd_selftest(args) -> int:
    paths = [Path(p) for p in args.scenarios] or sorted(SCENARIOS.glob("*.yaml"))
    failed = 0
    for path in paths:
        scn = scenario_mod.load(path)
        lines: list[str] = []
        log = lines.append if not args.verbose else print
        clock = FakeClock()
        bus = MemoryBus()
        key = bytes(range(32))
        hub = DevHub({args.node: key}, bus.client(), log=log)
        node = SimNode(args.node, key, bus.client(), log=log)
        attacker = Attacker(args.node, bus.client(), log=log, seed=0)
        hub.start()
        node.start()
        scenario_mod.run(scn, node, attacker, [hub.tick], clock.now, clock.sleep, log=log)
        failures = scenario_mod.check(scn, hub.kinds(), set(node.security_events))
        status = "PASS" if not failures else "FAIL"
        print(f"{status}  {scn.name:<18} {scn.description}")
        for f in failures:
            print(f"      - {f}")
        failed += bool(failures)
    return 1 if failed else 0


# --- live hub -----------------------------------------------------------------


def cmd_hub(args) -> int:
    secrets = load_secrets(args.secrets)
    host, port = broker(args, secrets)
    transport = MqttTransport(host, port, "hub", secrets["hub"]["password"], client_id="alarm-dev-hub")
    hub = DevHub(node_keys(secrets), transport, quiet_hb=not args.show_hb)
    hub.start()
    print(f"[hub] connected to {host}:{port}, nodes: {', '.join(secrets['nodes'])}")
    print("[hub] type: cmd <node> buzzer=1 led=alarm   |   quit")
    lines = _stdin_lines()
    try:
        while True:
            for line in _drain(lines):
                parts = line.split()
                if parts[:1] == ["quit"]:
                    return 0
                if len(parts) >= 3 and parts[0] == "cmd":
                    fields = dict(p.split("=", 1) for p in parts[2:])
                    fields = {"id": str(int(time.time()) % 100000), **fields}
                    if not hub.command(parts[1], fields):
                        print(f"[hub] no session with {parts[1]}")
                elif parts:
                    print("usage: cmd <node> key=value ...")
            hub.tick(time.monotonic())
            time.sleep(0.05)
    except KeyboardInterrupt:
        return 0
    finally:
        transport.close()


# --- live node ----------------------------------------------------------------

NODE_HELP = """commands:
  <sensor> <value>      set a sensor: 0|1 for on/off ones, a number for the others ({sensors})
  jam <seconds>         radio silence, then reconnect
  reboot [seconds]      reboot (default 2 s offline)
  attack <name> [k=v]   {', '.join(ATTACKS)}
  status | help | quit"""


def cmd_node(args) -> int:
    secrets = load_secrets(args.secrets)
    host, port = broker(args, secrets)
    cfg = secrets["nodes"].get(args.node)
    if cfg is None:
        sys.exit(f"node {args.node!r} not in {args.secrets}")
    transport = MqttTransport(
        host, port, args.node, cfg["password"], client_id=f"sim-{args.node}",
        will=(status_topic(args.node), "offline"),
    )
    module = None
    try:
        module = load_modules(args.modules).modules.get(args.node)
    except ModuleError as e:
        print(f"[{args.node}] {e}")
    if module is None:
        print(f"[{args.node}] not described in {args.modules}: simulating a door module")
    node = SimNode(args.node, bytes.fromhex(cfg["key"]), transport, module=module)
    print(f"[{args.node}] {node.module.type} module, sensors: " + ", ".join(
        f"{n} ({'0/1' if s.binary else s.unit or 'number'})" for n, s in node.module.sensors.items()))
    attacker = None
    if "attacker" in secrets:
        a_transport = MqttTransport(host, port, "attacker", secrets["attacker"]["password"], client_id=f"attacker-{args.node}")
        attacker = Attacker(args.node, a_transport)
        a_transport.connect()
    control = SimControl(node, attacker)  # lets the dashboard drive this node (sim/<node>/cmd)
    node.start()
    print(f"[{args.node}] connecting to {host}:{port}")
    try:
        if args.scenario:
            scn = scenario_mod.load(args.scenario)
            scenario_mod.run(scn, node, attacker, [control.tick], time.monotonic, time.sleep)
            return 0
        if args.headless:
            return _headless(node, control)
        return _interactive(node, attacker, control)
    except KeyboardInterrupt:
        return 0
    finally:
        transport.close()
        if attacker:
            attacker.transport.close()


def _interactive(node: SimNode, attacker: Attacker | None, control: SimControl) -> int:
    print(NODE_HELP.format(sensors=", ".join(node.module.sensors)))
    lines = _stdin_lines()
    while True:
        now = time.monotonic()
        for line in _drain(lines):
            try:
                if _node_command(node, attacker, shlex.split(line), now) == "quit":
                    return 0
            except (ValueError, RuntimeError) as e:
                print(f"error: {e}")
        node.tick(now)
        control.tick(now)
        time.sleep(0.05)


def _headless(node: SimNode, control: SimControl) -> int:
    """No terminal input: driven only by the dashboard (or run in Docker)."""
    print(f"[{node.node_id}] headless: control it from the dashboard (sim/{node.node_id}/cmd)")
    while True:
        now = time.monotonic()
        node.tick(now)
        control.tick(now)
        time.sleep(0.05)


def _node_command(node: SimNode, attacker: Attacker | None, parts: list[str], now: float):
    if not parts:
        return None
    cmd, rest = parts[0], parts[1:]
    if cmd == "quit":
        return "quit"
    if cmd == "help":
        print(NODE_HELP.format(sensors=", ".join(node.module.sensors)))
    elif cmd == "status":
        sid = node.channel.keys.sid if node.channel else "-"
        print(f"state={node.state} session={sid} sensors={node.sensors} outputs={node.outputs}")
    elif cmd in node.module.sensors and len(rest) == 1:
        node.set(now, **{cmd: rest[0]})
    elif cmd == "jam" and len(rest) == 1:
        node.jam(now, float(rest[0]))
    elif cmd == "reboot":
        node.reboot(now, float(rest[0]) if rest else 2.0)
    elif cmd == "attack" and rest:
        if attacker is None:
            raise RuntimeError("no 'attacker' credentials in secrets file")
        kwargs = {}
        for kv in rest[1:]:
            k, _, v = kv.partition("=")
            kwargs[k] = int(v) if v.lstrip("-").isdigit() else v
        attacker.run(rest[0], **kwargs)
    else:
        print("unknown command, type 'help'")
    return None


def _stdin_lines():
    q: queue.SimpleQueue = queue.SimpleQueue()

    def reader():
        for line in sys.stdin:
            q.put(line.strip())
        q.put("quit")

    threading.Thread(target=reader, daemon=True).start()
    return q


def _drain(q):
    while True:
        try:
            yield q.get_nowait()
        except queue.Empty:
            return


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="alarm-sim", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--secrets", type=Path, default=DEFAULT_SECRETS, help="dev secrets JSON (default: .secrets/dev.json)")
    p.add_argument("--broker", help="host[:port], overrides the secrets file")
    sub = p.add_subparsers(dest="cmd", required=True)

    st = sub.add_parser("selftest", help="run scenarios offline against the in-memory hub")
    st.add_argument("scenarios", nargs="*", help="scenario files (default: all)")
    st.add_argument("--node", default="door-1")
    st.add_argument("-v", "--verbose", action="store_true")

    h = sub.add_parser("hub", help="dev hub on the MQTT broker")
    h.add_argument("--show-hb", action="store_true", help="print every heartbeat")

    n = sub.add_parser("node", help="simulated node on the MQTT broker")
    n.add_argument("--node", default="door-1")
    n.add_argument("--scenario", help="run a scenario file instead of interactive mode")
    n.add_argument("--headless", action="store_true", help="no terminal input; control from the dashboard only")
    n.add_argument("--modules", type=Path, default=DEFAULT_MODULES, help="module descriptions (config/modules.yaml)")

    args = p.parse_args(argv)
    return {"selftest": cmd_selftest, "hub": cmd_hub, "node": cmd_node}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())

"""alarm-core against the simulated node and attacker, on the in-memory bus."""

import json

import pytest

from alarm_core.codes import CodeChecker, hash_code
from alarm_core.machine import ARMED, DISARMED, ENTRY_DELAY, TRIGGERED, AlarmMachine, Timing
from alarm_core.service import CONTROL_TOPIC, EVENTS_TOPIC, STATE_TOPIC, AlarmService
from alarm_protocol.transport import MemoryBus
from alarm_sim.__main__ import FakeClock
from alarm_sim.attacks import Attacker
from alarm_sim.node import SimNode

KEY = bytes(range(32))
NODE = "door-1"


class Rig:
    def __init__(self):
        quiet = lambda _m: None
        self.bus = MemoryBus()
        self.clock = FakeClock()
        codes = CodeChecker([hash_code("1234", 1000)], [hash_code("9999", 1000)])
        self.machine = AlarmMachine([NODE], codes, Timing(exit_delay=10, entry_delay=10, siren_max=60))
        self.service = AlarmService({NODE: KEY}, self.machine, self.bus.client(), log=quiet, wall=lambda: 0.0)
        self.node = SimNode(NODE, KEY, self.bus.client(), log=quiet)
        self.attacker = Attacker(NODE, self.bus.client(), log=quiet, seed=0)
        self.ctl = self.bus.client()
        self.events: list[dict] = []
        self.ctl.subscribe(EVENTS_TOPIC, lambda _t, p: self.events.append(json.loads(p)))
        self.service.start()
        self.node.start()

    def run(self, seconds: float) -> None:
        end = self.clock.t + seconds
        while self.clock.t < end:
            self.node.tick(self.clock.t)
            self.service.tick(self.clock.t)
            self.clock.sleep(0.05)

    def control(self, **msg) -> None:
        self.ctl.publish(CONTROL_TOPIC, json.dumps({"source": "test", **msg}))
        self.run(0.1)

    def kinds(self) -> list[str]:
        return [e["type"] for e in self.events]


@pytest.fixture
def rig():
    r = Rig()
    r.run(2)  # handshake + first heartbeats
    return r


def arm(rig):
    rig.control(action="arm", code="1234")
    rig.run(10.5)
    assert rig.machine.state == ARMED


def test_full_intrusion_rings_the_node_buzzer(rig):
    arm(rig)
    assert rig.node.outputs["led"] == "armed"
    rig.node.set(rig.clock.t, door=1)
    rig.run(0.2)
    assert rig.machine.state == ENTRY_DELAY
    rig.run(10.5)
    assert rig.machine.state == TRIGGERED
    assert rig.node.outputs == {"buzzer": "1", "led": "alarm"}

    rig.control(action="disarm", code="1234")
    rig.run(0.2)
    assert rig.machine.state == DISARMED
    assert rig.node.outputs == {"buzzer": "0", "led": "off"}


def test_disarm_during_entry_delay_never_rings(rig):
    arm(rig)
    rig.node.set(rig.clock.t, door=1)
    rig.run(5)
    rig.control(action="disarm", code="1234")
    rig.run(10)
    assert rig.machine.state == DISARMED
    assert "triggered" not in [e.get("state") for e in rig.events]


def test_jamming_while_armed_triggers(rig):
    arm(rig)
    rig.node.jam(rig.clock.t, 6)
    rig.run(4)
    assert rig.machine.state == TRIGGERED and rig.machine.reason == "link_lost"
    rig.run(4)  # link comes back with a new session; outputs are resent
    assert rig.node.outputs["buzzer"] == "1"


def test_spoofed_door_closed_is_reported_not_believed(rig):
    arm(rig)
    rig.node.set(rig.clock.t, door=1)
    rig.run(0.5)
    rig.attacker.run("spoof")  # forged "door=0"
    rig.run(0.5)
    sec = [e for e in rig.events if e["type"] == "security"]
    assert sec and sec[-1]["kind"] == "auth_fail"
    assert rig.machine.sensors[NODE]["door"] == "1"
    assert rig.machine.state == ENTRY_DELAY


def test_bad_codes_and_garbage_control_messages(rig):
    rig.control(action="arm", code="0000", req="r1")
    assert rig.events[-1]["type"] == "bad_code" and rig.events[-1]["req"] == "r1"
    rig.ctl.publish(CONTROL_TOPIC, b"not json")
    rig.ctl.publish(CONTROL_TOPIC, b"[1,2]")
    rig.ctl.publish(CONTROL_TOPIC, json.dumps({"action": "arm", "code": "1234", "pad": "x" * 600}))
    rig.run(0.2)
    assert rig.machine.state == DISARMED


def test_status_and_retained_state(rig):
    rig.control(action="status", req="s1")
    status = rig.events[-1]
    assert status["type"] == "status" and status["nodes"][NODE]["online"]
    states = [json.loads(p) for t, p in rig.bus.log if t == STATE_TOPIC]
    assert states[-1]["state"] == DISARMED


def test_lost_command_is_repaired_by_keepalive(rig):
    arm(rig)
    rig.node.outputs["led"] = "off"  # pretend the CMD never arrived
    rig.run(5.5)
    assert rig.node.outputs["led"] == "armed"


def test_events_are_logged_and_head_published(tmp_path):
    from alarm_core.eventlog import EventLog, verify

    path = tmp_path / "events.jsonl"
    r = Rig()
    r.service.eventlog = EventLog(path, b"k" * 32)
    r.run(2)
    arm(r)
    result = verify(path, b"k" * 32)
    assert result.ok and result.count >= 3
    state = [json.loads(p) for t, p in r.bus.log if t == STATE_TOPIC][-1]
    assert state["log"] == {"seq": result.head_seq, "head": result.head_mac}


def test_tampered_log_raises_event_at_startup(tmp_path):
    from alarm_core.eventlog import EventLog

    path = tmp_path / "events.jsonl"
    lg = EventLog(path, b"k" * 32)
    for i in range(3):
        lg.append({"type": "sensor", "n": i})
    path.write_text("\n".join(path.read_text().splitlines()[1:]) + "\n")  # delete record 1

    bus = MemoryBus()
    codes = CodeChecker([hash_code("1234", 1000)], [])
    service = AlarmService({NODE: KEY}, AlarmMachine([NODE], codes), bus.client(), log=lambda _m: None,
                           wall=lambda: 0.0, eventlog=EventLog(path, b"k" * 32))
    service.tick(0)
    assert service.published[0]["type"] == "log_tampered"

from pathlib import Path

import pytest

from alarm_protocol.hub import Hub
from alarm_sim import scenario
from alarm_sim.__main__ import FakeClock, main
from alarm_sim.attacks import Attacker
from alarm_sim.devhub import DevHub
from alarm_sim.node import SimNode
from alarm_sim.transport import MemoryBus, topic_matches

SCENARIOS = sorted((Path(__file__).resolve().parents[1] / "scenarios").glob("*.yaml"))
KEY = bytes(range(32))
NODE = "door-1"


def rig():
    bus = MemoryBus()
    clock = FakeClock()
    quiet = lambda _msg: None
    hub = DevHub({NODE: KEY}, bus.client(), log=quiet)
    node = SimNode(NODE, KEY, bus.client(), log=quiet)
    attacker = Attacker(NODE, bus.client(), log=quiet, seed=0)
    hub.start()
    node.start()

    def advance(seconds):
        end = clock.t + seconds
        while clock.t < end:
            node.tick(clock.t)
            hub.tick(clock.t)
            clock.sleep(0.05)

    return bus, clock, hub, node, attacker, advance


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
def test_scenario_expectations(path, capsys):
    assert main(["selftest", str(path)]) == 0, capsys.readouterr().out


def test_session_established_and_heartbeats():
    _, _, hub, node, _, advance = rig()
    advance(3)
    assert node.state == "session"
    beats = [e for e in hub.events if e.kind == "msg" and e.message.type == "HB"]
    assert len(beats) >= 2
    assert beats[-1].message.fields["door"] == "0"


def test_command_reaches_node_and_is_acked():
    _, _, hub, node, _, advance = rig()
    advance(1)
    assert hub.command(NODE, {"id": "42", "buzzer": "1"})
    advance(0.2)
    assert node.outputs["buzzer"] == "1"
    acks = [e.message for e in hub.events if e.kind == "msg" and e.message.type == "ACK"]
    assert acks[-1].fields == {"id": "42", "ok": "1"}


def test_node_recovers_after_hub_restart():
    _, _, hub, node, _, advance = rig()
    advance(2)
    old_sid = node.channel.keys.sid
    hub.hub = Hub({NODE: KEY})  # hub process restarts, sessions lost
    advance(12)  # node notices the missing downlink after 10 s
    assert node.state == "session"
    assert node.channel.keys.sid != old_sid
    assert hub.hub.has_session(NODE)


def test_replayed_welcome_is_ignored():
    _, _, _, node, attacker, advance = rig()
    advance(2)
    sid = node.channel.keys.sid
    welcome = next(p for p in attacker.down if p.startswith("v1|WELCOME|"))
    node.transport.publish(f"alarm/v1/{NODE}/down", welcome)
    advance(1)
    assert node.channel.keys.sid == sid
    assert node.security_events == []


def test_sensor_change_sends_event_immediately():
    _, clock, hub, node, _, advance = rig()
    advance(1.5)
    node.set(clock.t, door=1)
    advance(0.05)
    evts = [e.message for e in hub.events if e.kind == "msg" and e.message.type == "EVT"]
    assert evts[-1].fields == {"door": "1"}


def test_bad_scenario_rejected(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("steps:\n  - at: 1\n    attack: nuke\n")
    with pytest.raises(ValueError):
        scenario.load(p)


@pytest.mark.parametrize(
    "pattern,topic,ok",
    [
        ("alarm/v1/+/up", "alarm/v1/door-1/up", True),
        ("alarm/v1/+/up", "alarm/v1/door-1/down", False),
        ("alarm/v1/#", "alarm/v1/door-1/up", True),
        ("alarm/v1/door-1/up", "alarm/v1/door-1/up/x", False),
    ],
)
def test_topic_matching(pattern, topic, ok):
    assert topic_matches(pattern, topic) is ok

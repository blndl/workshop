"""Node -> alarm-core -> camera -> alarm-core log, all on the in-memory bus."""

import hashlib

from alarm_camera.service import CameraService
from alarm_camera.sources import FakeSource
from alarm_camera.store import SnapshotStore
from alarm_core.codes import CodeChecker, hash_code
from alarm_core.eventlog import EventLog, verify
from alarm_core.machine import AlarmMachine, Timing
from alarm_core.service import AlarmService
from alarm_protocol.transport import MemoryBus
from alarm_sim.__main__ import FakeClock
from alarm_sim.node import SimNode

KEY = bytes(range(32))


def test_intrusion_produces_logged_snapshots(tmp_path):
    quiet = lambda _m: None
    bus, clock = MemoryBus(), FakeClock()
    codes = CodeChecker([hash_code("1234", 1000)], [])
    machine = AlarmMachine(["door-1"], codes, Timing(exit_delay=2, entry_delay=3))
    log = EventLog(tmp_path / "events.jsonl", b"k" * 32)
    core = AlarmService({"door-1": KEY}, machine, bus.client(), log=quiet, eventlog=log)
    source = FakeSource(b"\xff\xd8 fake jpeg")
    camera = CameraService(source, SnapshotStore(tmp_path / "snaps"), bus.client(), log=quiet)
    node = SimNode("door-1", KEY, bus.client(), log=quiet)
    core.start(), camera.start(), node.start()

    def run(seconds):
        end = clock.t + seconds
        while clock.t < end:
            node.tick(clock.t), core.tick(clock.t), camera.tick(clock.t)
            clock.sleep(0.05)

    run(2)
    assert not source.is_open  # disarmed: camera off
    machine.arm("1234", clock.t, "test")
    run(3)
    assert source.is_open
    node.set(clock.t, door=1)
    run(5)  # entry delay runs out -> triggered
    assert machine.state == "triggered"

    snaps = [e for e in core.published if e["type"] == "snapshot"]
    assert len(snaps) >= 6  # door + entry burst + alarm burst
    for e in snaps:
        image = (tmp_path / "snaps" / e["path"]).read_bytes()
        assert hashlib.sha256(image).hexdigest() == e["sha256"]
    assert verify(log.path, b"k" * 32).ok

    machine.disarm("1234", clock.t, "test")
    run(2)
    assert not source.is_open

"""Node -> alarm-core -> camera -> notifier, all on the in-memory bus."""

from alarm_camera.service import CameraService
from alarm_camera.sources import FakeSource
from alarm_camera.store import SnapshotStore
from alarm_core.codes import CodeChecker, hash_code
from alarm_core.machine import AlarmMachine, Timing
from alarm_core.service import AlarmService
from alarm_notifier.service import NotifierService
from alarm_protocol.transport import MemoryBus
from alarm_sim.__main__ import FakeClock
from alarm_sim.node import SimNode

KEY = bytes(range(32))


class Phone:
    def __init__(self):
        self.alerts = []

    def send(self, alert):
        self.alerts.append(alert)


def test_intrusion_reaches_the_phone_with_a_photo(tmp_path):
    quiet = lambda _m: None
    bus, clock, phone = MemoryBus(), FakeClock(), Phone()
    codes = CodeChecker([hash_code("1234", 1000)], [hash_code("9999", 1000)])
    machine = AlarmMachine(["door-1"], codes, Timing(exit_delay=2, entry_delay=3))
    services = [
        AlarmService({"door-1": KEY}, machine, bus.client(), log=quiet),
        CameraService(FakeSource(b"jpeg"), SnapshotStore(tmp_path), bus.client(), log=quiet),
        NotifierService(phone, bus.client(), tmp_path, log=quiet),
    ]
    node = SimNode("door-1", KEY, bus.client(), log=quiet)
    for s in services:
        s.start()
    node.start()

    def run(seconds):
        end = clock.t + seconds
        while clock.t < end:
            node.tick(clock.t)
            for s in services:
                s.tick(clock.t)
            clock.sleep(0.05)

    run(2)
    machine.arm("1234", clock.t, "test")
    run(3)
    node.set(clock.t, door=1)
    run(6)
    alarm = [a for a in phone.alerts if a.title == "ALARM"]
    assert len(alarm) == 1 and alarm[0].priority == 5
    assert alarm[0].image is not None and alarm[0].image.read_bytes() == b"jpeg"
    assert "alarm-" in alarm[0].image.name

    machine.disarm("9999", clock.t, "keypad")  # duress
    run(3)
    titles = [a.title for a in phone.alerts]
    assert "DURESS CODE USED" in titles and "Disarmed" in titles
    duress = next(a for a in phone.alerts if a.title == "DURESS CODE USED")
    assert duress.image is not None and "duress" in duress.image.name

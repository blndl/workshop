"""The API against the real alarm-core and a simulated node, on the in-memory bus."""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from alarm_api.app import create_app
from alarm_api.bridge import Bridge
from alarm_core.codes import CodeChecker, hash_code
from alarm_core.machine import AlarmMachine, Timing
from alarm_core.service import AlarmService
from alarm_protocol.transport import MemoryBus
from alarm_sim.node import SimNode

KEY = bytes(range(32))
quiet = lambda _m: None


class House:
    """alarm-core + one node, ticked in real time by a background thread."""

    def __init__(self, bus: MemoryBus, with_node: bool = True):
        codes = CodeChecker([hash_code("1234", 1000)], [hash_code("9999", 1000)])
        self.machine = AlarmMachine(["door-1"], codes, Timing(exit_delay=0.5, entry_delay=0.5))
        self.core = AlarmService({"door-1": KEY}, self.machine, bus.client(), log=quiet)
        self.node = SimNode("door-1", KEY, bus.client(), log=quiet) if with_node else None
        self._stop = threading.Event()
        self.core.start()
        if self.node:
            self.node.start()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not self._stop.is_set():
            now = time.monotonic()
            if self.node:
                self.node.tick(now)
            self.core.tick(now)
            time.sleep(0.01)

    def stop(self):
        self._stop.set()
        self.thread.join(1)


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def api():
    bus = MemoryBus()
    house = House(bus)
    with TestClient(create_app(Bridge(bus.client()))) as client:
        assert wait_for(lambda: house.machine.online["door-1"]), "node never came online"
        client.get("/api/state")
        yield client, house
    house.stop()


def test_health_and_state(api):
    client, _ = api
    assert wait_for(lambda: client.get("/api/state").status_code == 200)
    assert client.get("/api/health").json()["mqtt_connected"] is True
    state = client.get("/api/state").json()
    assert state["state"] == "disarmed" and state["nodes"]["door-1"]["online"] is True


def test_arm_then_disarm(api):
    client, house = api
    r = client.post("/api/arm", json={"code": "1234"})
    assert r.status_code == 200
    assert r.json() == {"result": "ok", "state": "arming", "prev": "disarmed", "delay": 0.5}
    assert wait_for(lambda: house.machine.state == "armed")
    r = client.post("/api/disarm", json={"code": "1234"})
    assert r.status_code == 200 and r.json()["state"] == "disarmed"


def test_wrong_code(api):
    client, _ = api
    r = client.post("/api/arm", json={"code": "0000"})
    assert r.status_code == 403 and r.json()["result"] == "bad_code"


def test_disarm_when_already_disarmed(api):
    client, _ = api
    r = client.post("/api/disarm", json={"code": "1234"})
    assert r.status_code == 200 and r.json() == {"result": "no_change"}


def test_duress_disarm_is_indistinguishable(api):
    client, house = api

    def disarm_with(code):
        client.post("/api/arm", json={"code": "1234"})
        wait_for(lambda: house.machine.state == "armed")
        r = client.post("/api/disarm", json={"code": code})
        return r.status_code, r.json()

    assert disarm_with("1234") == disarm_with("9999")
    events = client.get("/api/events?limit=500").json()
    assert all(e["type"] != "duress" for e in events)
    assert all(e["type"] not in ("control_done", "status") for e in events)


def test_lockout_after_five_wrong_codes(api):
    client, _ = api
    results = [client.post("/api/disarm", json={"code": "0000"}).json()["result"] for _ in range(5)]
    assert results == ["bad_code"] * 4 + ["lockout"]
    r = client.post("/api/disarm", json={"code": "1234"})
    assert r.status_code == 403 and r.json()["result"] == "locked"


def test_events_filter_and_order(api):
    client, house = api
    client.post("/api/arm", json={"code": "1234"})
    wait_for(lambda: house.machine.state == "armed")
    states = client.get("/api/events", params={"type": "state"}).json()
    assert [e["state"] for e in states[:2]] == ["armed", "arming"]  # newest first


@pytest.mark.parametrize("code", ["12", "123456789", "abcd", "12 34", ""])
def test_code_validation(api, code):
    client, _ = api
    assert client.post("/api/arm", json={"code": code}).status_code == 422


def test_arm_refused_when_node_offline():
    bus = MemoryBus()
    house = House(bus, with_node=False)
    with TestClient(create_app(Bridge(bus.client()))) as client:
        r = client.post("/api/arm", json={"code": "1234"})
        assert r.status_code == 409 and r.json()["detail"] == ["door-1 offline"]
    house.stop()


def test_alarm_core_down_gives_504():
    bus = MemoryBus()
    with TestClient(create_app(Bridge(bus.client(), timeout=0.3))) as client:
        assert client.get("/api/state").status_code == 503
        r = client.post("/api/arm", json={"code": "1234"})
        assert r.status_code == 504


def test_sim_panel_disabled_by_default(api):
    client, _ = api
    assert client.get("/api/sim").json() == {"enabled": False, "nodes": {}}
    assert client.post("/api/sim/door-1/command", json={"cmd": "jam", "seconds": 3}).status_code == 404


def test_sim_panel_drives_the_node():
    from alarm_sim.control import SimControl

    bus = MemoryBus()
    house = House(bus)
    control = SimControl(house.node, log=quiet)
    ticker = threading.Thread(target=lambda: [control.tick(time.monotonic()) or time.sleep(0.02) for _ in range(150)], daemon=True)
    ticker.start()
    with TestClient(create_app(Bridge(bus.client(), sim=True))) as client:
        assert wait_for(lambda: "door-1" in client.get("/api/sim").json()["nodes"])
        r = client.post("/api/sim/door-1/command", json={"cmd": "set", "sensor": "door", "value": 1})
        assert r.status_code == 202
        assert wait_for(lambda: client.get("/api/sim").json()["nodes"]["door-1"]["sensors"]["door"] == "1")
        assert wait_for(lambda: client.get("/api/state").json()["nodes"]["door-1"]["sensors"]["door"] == "1")
        bad = [{"cmd": "shell"}, {"cmd": "set", "sensor": "Door!", "value": 1}, {"cmd": "jam", "seconds": 600},
               {"cmd": "set", "sensor": "gas", "value": 1e9}]
        assert all(client.post("/api/sim/door-1/command", json=b).status_code == 422 for b in bad)
        assert client.post("/api/sim/..%2Fetc/command", json={"cmd": "jam", "seconds": 3}).status_code in (404, 422)
    house.stop()


def test_prometheus_metrics(api):
    client, house = api
    client.post("/api/arm", json={"code": "1234"})
    wait_for(lambda: house.machine.state == "armed")
    client.post("/api/disarm", json={"code": "9999"})  # duress
    wait_for(lambda: house.machine.state == "disarmed")
    assert wait_for(lambda: 'alarm_state_changes_total{state="disarmed"}' in client.get("/metrics").text)
    text = client.get("/metrics").text
    assert 'alarm_state{state="disarmed"} 1.0' in text
    assert 'alarm_node_online{node="door-1"} 1.0' in text
    assert 'alarm_node_rssi_dbm{node="door-1"}' in text
    assert 'alarm_state_changes_total{state="armed"} 1.0' in text
    assert 'alarm_api_request_duration_seconds_count{method="POST",route="/api/arm",status="200"}' in text
    assert "duress" not in text  # a forced disarm must not show anywhere


def test_info_without_grafana(api):
    client, _ = api
    assert client.get("/api/info").json() == {"grafana_url": None}


def test_access_log_quiets_polling():
    import logging

    from alarm_api.__main__ import _QuietPolling

    def record(method, path, status):
        return logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                                 ("1.2.3.4:5", method, path, "1.1", status), None)

    f = _QuietPolling()
    assert not f.filter(record("GET", "/metrics", 200))
    assert not f.filter(record("GET", "/api/events?limit=500", 200))
    assert f.filter(record("POST", "/api/arm", 200))        # changes are kept
    assert f.filter(record("GET", "/api/state", 503))       # errors are kept

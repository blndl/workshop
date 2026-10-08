import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from alarm_notifier.ntfy import NtfyBackend, SendError, header
from alarm_notifier.rules import Alert, Rules, build
from alarm_notifier.service import NotifierService
from alarm_protocol.transport import MemoryBus


class FakeBackend:
    def __init__(self, fail_times=0, permanent=False):
        self.sent, self.fail_times, self.permanent, self.calls = [], fail_times, permanent, 0

    def send(self, alert):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise SendError("boom", self.permanent)
        self.sent.append(alert)


def rig(tmp_path, backend=None):
    bus = MemoryBus()
    backend = backend or FakeBackend()
    svc = NotifierService(backend, bus.client(), tmp_path, log=lambda _m: None)
    pub = bus.client()
    return svc, backend, lambda e: pub.publish("alarm/events", json.dumps(e))


def run(svc, start, end, step=0.1):
    t = start
    while t <= end:
        svc.tick(t)
        t += step


# --- rules ---------------------------------------------------------------


def test_which_events_alert():
    assert build({"type": "state", "state": "triggered", "reason": "door", "node": "door-1"}).priority == 5
    assert build({"type": "duress", "source": "keypad"}).priority == 5
    assert build({"type": "security", "kind": "replay", "node": "door-1"}).priority == 4
    assert build({"type": "state", "state": "armed", "prev": "arming"}) is None
    assert build({"type": "sensor", "sensor": "pir", "value": "1"}) is None
    assert build({"type": "snapshot"}) is None


def test_non_urgent_repeats_throttled_with_count():
    r = Rules(throttle=60)
    e = {"type": "security", "kind": "auth_fail", "node": "door-1"}
    assert r.alert_for(e, 0) is not None
    assert r.alert_for(e, 1) is None and r.alert_for(e, 2) is None
    later = r.alert_for(e, 61)
    assert later.message.endswith("(+2 similar in the last minute)")


def test_urgent_never_throttled():
    r = Rules()
    e = {"type": "state", "state": "triggered", "reason": "door"}
    assert r.alert_for(e, 0) and r.alert_for(e, 1)


# --- service -------------------------------------------------------------


def test_alarm_waits_for_and_attaches_first_alarm_photo(tmp_path):
    (tmp_path / "day").mkdir()
    (tmp_path / "day" / "a.jpg").write_bytes(b"img")
    svc, backend, publish = rig(tmp_path)
    publish({"type": "state", "state": "triggered", "reason": "door"})
    svc.tick(0)
    assert backend.sent == []  # waiting for the photo
    publish({"type": "snapshot", "path": "day/entry.jpg", "reason": "entry-door-1"})  # not an alarm photo
    publish({"type": "snapshot", "path": "day/a.jpg", "reason": "alarm-door-1"})
    svc.tick(0.5)
    assert backend.sent[0].image == (tmp_path / "day" / "a.jpg").resolve()


def test_alarm_sent_without_photo_after_timeout(tmp_path):
    svc, backend, publish = rig(tmp_path)
    publish({"type": "state", "state": "triggered", "reason": "door"})
    run(svc, 0, 2.0)
    assert backend.sent == []
    run(svc, 2.1, 3.0)
    assert len(backend.sent) == 1 and backend.sent[0].image is None


def test_snapshot_path_cannot_escape_the_folder(tmp_path):
    svc, backend, publish = rig(tmp_path)
    publish({"type": "state", "state": "triggered", "reason": "door"})
    publish({"type": "snapshot", "path": "../../etc/passwd", "reason": "alarm-x"})
    svc.tick(0)
    assert backend.sent[0].image is None


def test_transient_failures_are_retried(tmp_path):
    svc, backend, publish = rig(tmp_path, FakeBackend(fail_times=3))
    publish({"type": "tamper", "node": "door-1", "sensor": "lid"})
    run(svc, 0, 10)
    assert backend.calls == 4 and len(backend.sent) == 1  # retries after 1, 2, 4 s


def test_permanent_failure_is_dropped(tmp_path):
    svc, backend, publish = rig(tmp_path, FakeBackend(fail_times=99, permanent=True))
    publish({"type": "tamper", "node": "door-1"})
    run(svc, 0, 10)
    assert backend.calls == 1 and backend.sent == []


# --- ntfy backend ----------------------------------------------------------


@pytest.fixture
def ntfy_server():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def _handle(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            requests.append((self.command, self.path, dict(self.headers), body))
            code = 503 if self.path.endswith("/down") else 403 if self.path.endswith("/denied") else 200
            self.send_response(code)
            self.end_headers()
            self.wfile.write(b"{}")

        do_POST = do_PUT = _handle

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", requests
    server.shutdown()


def test_ntfy_text_message(ntfy_server):
    url, reqs = ntfy_server
    NtfyBackend(url, "alarm", "tk_x").send(Alert("ALARM", "door opened", 5, ["rotating_light"]))
    method, path, headers, body = reqs[0]
    assert (method, path, body) == ("POST", "/alarm", b"door opened")
    assert headers["Title"] == "ALARM" and headers["Priority"] == "5"
    assert headers["Tags"] == "rotating_light" and headers["Authorization"] == "Bearer tk_x"


def test_ntfy_with_photo_and_unicode(ntfy_server, tmp_path):
    url, reqs = ntfy_server
    img = tmp_path / "snap.jpg"
    img.write_bytes(b"\xff\xd8jpeg")
    NtfyBackend(url, "alarm").send(Alert("Caméra", "porte ouverte\n2e ligne", 4, image=img))
    method, _, headers, body = reqs[0]
    assert method == "PUT" and body == b"\xff\xd8jpeg" and headers["Filename"] == "snap.jpg"
    assert "Authorization" not in headers
    decoded = base64.b64decode(headers["Message"][10:-2]).decode()
    assert decoded == "porte ouverte\n2e ligne"
    assert header("Caméra") != "Caméra" and header("plain") == "plain"


def test_ntfy_errors_classified(ntfy_server):
    url, _ = ntfy_server
    with pytest.raises(SendError) as e:
        NtfyBackend(url, "down").send(Alert("t", "m"))
    assert not e.value.permanent
    with pytest.raises(SendError) as e:
        NtfyBackend(url, "denied").send(Alert("t", "m"))
    assert e.value.permanent
    with pytest.raises(SendError) as e:
        NtfyBackend("http://127.0.0.1:9", "x", timeout=1).send(Alert("t", "m"))
    assert not e.value.permanent


def test_safety_alerts():
    gas = build({"type": "safety_alarm", "node": "env-1", "sensor": "gas", "kind": "gas", "value": "650.0",
                 "unit": "ppm", "threshold": 400.0})
    assert gas.priority == 5 and gas.title == "SAFETY ALARM: gas"
    assert gas.message.startswith("650.0 ppm (limit 400 ppm) on env-1 (gas).")
    assert build({"type": "safety_clear", "node": "env-1", "sensor": "gas", "value": "120.0"}).priority == 3
    assert build({"type": "safety_silenced", "source": "api", "alarms": ["env-1 gas"]}).priority == 3

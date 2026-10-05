import os

from alarm_protocol import Channel, b64d, b64e, derive_session, sign, verify_signed
from alarm_protocol.hub import Hub, down_topic

MASTER = os.urandom(32)
NODE = "door-1"


def kinds(r):
    return [e.kind for e in r.events]


def connect(hub, now=0.0, nn=None):
    """Node side of the handshake against `hub`. Returns the node Channel."""
    nn = nn or os.urandom(16)
    r = hub.receive(NODE, sign(MASTER, NODE, "HELLO", {"fw": "0.1.0", "nn": b64e(nn)}), now)
    (topic, welcome), = r.replies
    assert topic == down_topic(NODE)
    pn = b64d(verify_signed(MASTER, NODE, welcome).fields["pn"])
    return Channel(derive_session(MASTER, NODE, nn, pn), NODE, "node")


def test_session_starts_on_first_sealed_message():
    hub = Hub({NODE: MASTER})
    node = connect(hub)
    assert not hub.has_session(NODE)
    r = hub.receive(NODE, node.seal("HB", {"door": "0"}), 0.1)
    assert kinds(r) == ["session_started", "msg"]
    assert hub.has_session(NODE)


def test_replayed_hello_does_not_break_current_session():
    hub = Hub({NODE: MASTER})
    nn = os.urandom(16)
    hello = sign(MASTER, NODE, "HELLO", {"nn": b64e(nn)})
    node = connect(hub, 0.0, nn)
    hub.receive(NODE, node.seal("HB", {}), 0.1)

    r = hub.receive(NODE, hello, 5.0)  # attacker replays the old HELLO
    assert kinds(r) == ["session_pending"]
    assert kinds(hub.receive(NODE, node.seal("HB", {}), 5.1)) == ["msg"]


def test_hello_retry_gets_same_welcome():
    hub = Hub({NODE: MASTER})
    hello = sign(MASTER, NODE, "HELLO", {"nn": b64e(os.urandom(16))})
    first = hub.receive(NODE, hello, 0.0).replies
    assert hub.receive(NODE, hello, 2.0).replies == first


def test_hello_rate_limit_counts_only_valid():
    hub = Hub({NODE: MASTER})
    forged = sign(os.urandom(32), NODE, "HELLO", {"nn": b64e(os.urandom(16))})
    assert kinds(hub.receive(NODE, forged, 0.0)) == ["auth_fail"]
    connect(hub, 0.1)  # real node is not blocked by the forgery
    assert kinds(hub.receive(NODE, sign(MASTER, NODE, "HELLO", {"nn": b64e(os.urandom(16))}), 0.5)) == ["rate_limited"]


def test_link_lost_and_restored():
    hub = Hub({NODE: MASTER})
    node = connect(hub)
    hub.receive(NODE, node.seal("HB", {}), 0.0)
    assert hub.check_links(2.9) == []
    assert [e.kind for e in hub.check_links(3.5)] == ["link_lost"]
    assert hub.check_links(10.0) == []  # only reported once
    assert kinds(hub.receive(NODE, node.seal("HB", {}), 11.0)) == ["link_restored", "msg"]


def test_unknown_node_and_wrong_direction():
    hub = Hub({NODE: MASTER})
    assert kinds(hub.receive("intruder", "v1|HB|00000000|1|AAAA", 0)) == ["unknown_node"]
    welcome = sign(MASTER, NODE, "WELCOME", {"nn": "x", "pn": "y"})
    assert kinds(hub.receive(NODE, welcome, 0)) == ["malformed"]


def test_downlink_requires_session():
    hub = Hub({NODE: MASTER})
    assert hub.send(NODE, "CMD", {"id": "0"}) is None
    node = connect(hub)
    hub.receive(NODE, node.seal("HB", {}), 0)
    _, payload = hub.send(NODE, "CMD", {"id": "0"})
    assert node.open(payload).fields == {"id": "0"}

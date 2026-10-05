import json
import os
from pathlib import Path

import pytest

import gen_vectors
from alarm_protocol import (
    MAX_PAYLOAD,
    AuthFail,
    Channel,
    Malformed,
    Replay,
    UnknownSession,
    b64d,
    b64e,
    derive_session,
    open_sealed,
    parse_fields,
    sign,
    verify_signed,
)

MASTER = os.urandom(32)
NODE = "door-1"


def handshake(master=MASTER, node=NODE):
    """Run HELLO/WELCOME and return (node_channel, hub_channel)."""
    nn = os.urandom(16)
    hello = sign(master, node, "HELLO", {"fw": "0.1.0", "nn": b64e(nn)})

    got = verify_signed(master, node, hello)  # hub side
    pn = os.urandom(16)
    welcome = sign(master, node, "WELCOME", {"nn": got.fields["nn"], "pn": b64e(pn)})
    hub_keys = derive_session(master, node, b64d(got.fields["nn"]), pn)

    w = verify_signed(master, node, welcome)  # node side
    assert w.fields["nn"] == b64e(nn)
    node_keys = derive_session(master, node, nn, b64d(w.fields["pn"]))

    assert node_keys == hub_keys
    return Channel(node_keys, node, "node"), Channel(hub_keys, node, "hub")


def test_roundtrip_both_directions():
    node, hub = handshake()
    m = hub.open(node.seal("HB", {"door": "0", "pir": "1", "rssi": "-61"}))
    assert (m.type, m.ctr, m.fields) == ("HB", 1, {"door": "0", "pir": "1", "rssi": "-61"})
    c = node.open(hub.seal("CMD", {"id": "7", "buzzer": "1"}))
    assert c.fields == {"id": "7", "buzzer": "1"}


def test_payload_hides_sensor_state():
    node, _ = handshake()
    assert "door" not in node.seal("EVT", {"door": "1"})


def test_replay_rejected():
    node, hub = handshake()
    msg = node.seal("EVT", {"door": "1"})
    hub.open(msg)
    with pytest.raises(Replay):
        hub.open(msg)


def test_older_counter_rejected():
    node, hub = handshake()
    first = node.seal("HB", {})
    hub.open(node.seal("HB", {}))
    with pytest.raises(Replay):
        hub.open(first)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.replace("|EVT|", "|HB|"),  # change type
        lambda p: p.replace("|1|", "|2|", 1),  # change counter
        lambda p: p[:-2] + ("A" if p[-2] != "A" else "B") + p[-1],  # flip ciphertext
    ],
)
def test_tampering_detected(mutate):
    node, hub = handshake()
    msg = node.seal("EVT", {"door": "0"})
    with pytest.raises(AuthFail):
        hub.open(mutate(msg))


def test_wrong_node_topic_rejected():
    node, hub = handshake()
    msg = node.seal("EVT", {"door": "0"})
    with pytest.raises(AuthFail):
        open_sealed(hub.keys.up, "door-2", msg)


def test_previous_session_rejected():
    old_node, _ = handshake()
    _, hub = handshake()
    with pytest.raises(UnknownSession):
        hub.open(old_node.seal("HB", {}))


def test_previous_session_rejected_even_if_sid_collides():
    old_node, _ = handshake()
    _, hub = handshake()
    hub.keys = type(hub.keys)(old_node.keys.sid, hub.keys.up, hub.keys.down)
    with pytest.raises(AuthFail):
        hub.open(old_node.seal("HB", {}))


def test_spoofed_hello_rejected():
    forged = sign(os.urandom(32), NODE, "HELLO", {"fw": "0.1.0", "nn": b64e(os.urandom(16))})
    with pytest.raises(AuthFail):
        verify_signed(MASTER, NODE, forged)


def test_hello_bound_to_node():
    hello = sign(MASTER, NODE, "HELLO", {"nn": b64e(os.urandom(16))})
    with pytest.raises(AuthFail):
        verify_signed(MASTER, "door-2", hello)


def test_direction_enforced():
    node, hub = handshake()
    downlink_from_attacker = Channel(hub.keys, NODE, "hub").seal("CMD", {"id": "1"})
    with pytest.raises(Malformed):
        hub.open(downlink_from_attacker)  # hub never accepts CMD
    with pytest.raises(ValueError):
        node.seal("CMD", {"id": "1"})


@pytest.mark.parametrize(
    "payload",
    [
        b"x" * (MAX_PAYLOAD + 1),
        b"\xff\xfe",
        "v2|HB|00000000|1|AAAA",
        "v1|NOPE|00000000|1|AAAA",
        "v1|HB|00000000|01|AAAA",
        "v1|HB|0000000|1|AAAA",
        "v1|HB|00000000|0|AAAA",
        "v1|HB|00000000|1",
        "v1|HB|00000000|1|AAAA",  # too short for a tag
    ],
)
def test_malformed(payload):
    node, hub = handshake()
    with pytest.raises((Malformed, UnknownSession)):
        hub.open(payload)


@pytest.mark.parametrize("text", ["a", "a=", "=1", "A=1", "a=1,a=2", "a=b c", "a=1,"])
def test_bad_fields(text):
    with pytest.raises(Malformed):
        parse_fields(text)


def test_typical_heartbeat_fits():
    node, _ = handshake(node="garage-door-rear")
    msg = node.seal("HB", {"door": "0", "pir": "0", "lid": "0", "up": "4294967295", "rssi": "-100"})
    assert len(msg) <= MAX_PAYLOAD


def test_vectors_file_matches_codec():
    path = Path(__file__).resolve().parents[2] / "test-vectors.json"
    assert json.loads(path.read_text()) == gen_vectors.build()

"""Regenerate ../test-vectors.json from fixed inputs. Run after any codec change."""

import json
from pathlib import Path

from alarm_protocol import Channel, b64e, derive_session, hello_key, sign

MASTER = bytes(range(32))
NODE = "door-1"
NN = bytes(range(0, 16))
PN = bytes(range(16, 32))


def build() -> dict:
    keys = derive_session(MASTER, NODE, NN, PN)
    node = Channel(keys, NODE, "node")
    hub = Channel(keys, NODE, "hub")
    return {
        "inputs": {"master_hex": MASTER.hex(), "node": NODE, "nn_hex": NN.hex(), "pn_hex": PN.hex()},
        "derived": {
            "k_hello_hex": hello_key(MASTER).hex(),
            "sid": keys.sid,
            "k_up_hex": keys.up.hex(),
            "k_down_hex": keys.down.hex(),
        },
        "messages": [
            {"topic": f"alarm/v1/{NODE}/up", "payload": sign(MASTER, NODE, "HELLO", {"fw": "0.1.0", "nn": b64e(NN)})},
            {"topic": f"alarm/v1/{NODE}/down", "payload": sign(MASTER, NODE, "WELCOME", {"nn": b64e(NN), "pn": b64e(PN)})},
            {"topic": f"alarm/v1/{NODE}/up", "plaintext": "door=0,pir=0,lid=0,up=12,rssi=-61",
             "payload": node.seal("HB", {"door": "0", "pir": "0", "lid": "0", "up": "12", "rssi": "-61"})},
            {"topic": f"alarm/v1/{NODE}/up", "plaintext": "pir=1", "payload": node.seal("EVT", {"pir": "1"})},
            {"topic": f"alarm/v1/{NODE}/down", "plaintext": "id=1,buzzer=1", "payload": hub.seal("CMD", {"id": "1", "buzzer": "1"})},
            {"topic": f"alarm/v1/{NODE}/up", "plaintext": "id=1,ok=1", "payload": node.seal("ACK", {"id": "1", "ok": "1"})},
        ],
    }


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "test-vectors.json"
    out.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {out}")

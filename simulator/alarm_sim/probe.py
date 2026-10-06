"""Segmentation probe: run on the 'iot' network (scripts/sim.sh probe).

A compromised device on the house Wi-Fi should reach the broker and nothing
else. Exits 1 if anything else answers.
"""

import socket
import sys

TARGETS = [
    ("mosquitto", 1883, True, "broker: nodes must reach it"),
    ("api", 8000, False, "web API / dashboard"),
    ("ntfy", 80, False, "alert server"),
    ("alarm-core", 1883, False, "alarm-core (no listening port at all)"),
]


def reachable(host: str, port: int) -> str:
    try:
        with socket.create_connection((host, port), timeout=2):
            return "open"
    except socket.gaierror:
        return "unknown host"
    except OSError:
        return "blocked"


def main() -> int:
    bad = 0
    print("From the iot network (a device on the house Wi-Fi):")
    for host, port, expected, what in TARGETS:
        result = reachable(host, port)
        ok = (result == "open") == expected
        bad += not ok
        print(f"  {'OK  ' if ok else 'FAIL'} {f'{host}:{port}':<17} {result:<13} {what}")
    print("segmentation OK" if not bad else f"{bad} unexpected result(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env bash
# Generate dev secrets: per-node master keys, broker passwords, alarm codes, log key.
#   scripts/dev-secrets.sh [node ...]     (default: door-1)
# Existing values in .secrets/dev.json are kept; only missing ones are added
# (FORCE=1 regenerates everything). Writes .secrets/dev.json and
# .secrets/mosquitto/passwd. Never commit these.
set -euo pipefail
cd "$(dirname "$0")/.."

[[ $# -eq 0 ]] && set -- door-1
mkdir -p .secrets/mosquitto
chmod 700 .secrets
[[ "${FORCE:-}" == 1 ]] && rm -f .secrets/dev.json

python3 - "$@" <<'PY'
import hashlib, json, os, secrets, sys
from pathlib import Path

path = Path(".secrets/dev.json")
d = json.loads(path.read_text()) if path.exists() else {}
pw = lambda: secrets.token_urlsafe(18)

def code_hash(code):
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", code.encode(), salt, 200_000)
    return f"pbkdf2_sha256$200000${salt.hex()}${h.hex()}"

d.setdefault("broker", {"host": "127.0.0.1", "port": 1883})
for account in ("hub", "ctl", "camera", "notifier", "attacker"):
    d.setdefault(account, {"password": pw()})
nodes = d.setdefault("nodes", {})
for n in sys.argv[1:]:
    nodes.setdefault(n, {"key": secrets.token_hex(32), "password": pw()})
d.setdefault("log_key", secrets.token_hex(32))
# DEV ONLY codes: 1234 disarms, 9999 is the duress code.
d.setdefault("codes", {"user": [code_hash("1234")], "duress": [code_hash("9999")]})

path.write_text(json.dumps(d, indent=2) + "\n")
path.chmod(0o600)

users = {a: d[a]["password"] for a in ("hub", "ctl", "camera", "notifier", "attacker")}
users |= {n: v["password"] for n, v in nodes.items()}
Path(".secrets/mosquitto/passwd").write_text("".join(f"{u}:{p}\n" for u, p in users.items()))
print("accounts:", ", ".join(users))
PY

# Hash the passwords with the broker's own tool.
docker run --rm -v "$PWD/.secrets/mosquitto:/m" eclipse-mosquitto:2 \
  sh -c 'chmod 600 /m/passwd && mosquitto_passwd -U /m/passwd && chown 1883:1883 /m/passwd'

echo "wrote .secrets/dev.json and .secrets/mosquitto/passwd (dev codes: 1234 user, 9999 duress)"
echo "restart the broker to load new accounts: docker compose -f infra/docker/compose.dev.yml restart"

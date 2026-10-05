#!/usr/bin/env bash
# Generate dev secrets: per-node master keys and broker passwords.
#   scripts/dev-secrets.sh [node ...]     (default: door-1)
# Writes .secrets/dev.json and .secrets/mosquitto/passwd. Never commit these.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .secrets/dev.json && "${FORCE:-}" != 1 ]]; then
  echo ".secrets/dev.json already exists (FORCE=1 to regenerate)" >&2
  exit 1
fi
[[ $# -eq 0 ]] && set -- door-1

mkdir -p .secrets/mosquitto
chmod 700 .secrets

python3 - "$@" > .secrets/dev.json <<'PY'
import json, secrets, sys
pw = lambda: secrets.token_urlsafe(18)
print(json.dumps({
    "broker": {"host": "127.0.0.1", "port": 1883},
    "hub": {"password": pw()},
    "attacker": {"password": pw()},
    "nodes": {n: {"key": secrets.token_hex(32), "password": pw()} for n in sys.argv[1:]},
}, indent=2))
PY
chmod 600 .secrets/dev.json

# Hash the passwords with the broker's own tool.
python3 -c '
import json
d = json.load(open(".secrets/dev.json"))
users = {"hub": d["hub"]["password"], "attacker": d["attacker"]["password"]}
users |= {n: v["password"] for n, v in d["nodes"].items()}
print("\n".join(f"{u}:{p}" for u, p in users.items()))
' > .secrets/mosquitto/passwd
docker run --rm -v "$PWD/.secrets/mosquitto:/m" eclipse-mosquitto:2 \
  sh -c 'chmod 600 /m/passwd && mosquitto_passwd -U /m/passwd && chown 1883:1883 /m/passwd'

echo "wrote .secrets/dev.json and .secrets/mosquitto/passwd for: $*"

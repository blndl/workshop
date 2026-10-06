#!/usr/bin/env bash
# Start the dev ntfy server and create its accounts:
#   notifier: write-only token for the "alarm" topic (used by the notifier)
#   phone:    read-only login for the ntfy app on your phone
# Saves them in .secrets/dev.json under "ntfy". Run scripts/dev-secrets.sh first.
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE=(docker compose -f infra/docker/compose.yml)
TOPIC=alarm

IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || true)
IP=${IP:-localhost}
echo "NTFY_BASE_URL=http://$IP:8080" > infra/docker/.env
"${COMPOSE[@]}" up -d ntfy
sleep 2

if python3 -c 'import json,sys; sys.exit(0 if "ntfy" in json.load(open(".secrets/dev.json")) else 1)' && [[ "${FORCE:-}" != 1 ]]; then
  echo "ntfy accounts already in .secrets/dev.json (FORCE=1 to recreate)"
else
  NOTIFIER_PW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')
  PHONE_PW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(9))')
  exec_ntfy() { "${COMPOSE[@]}" exec -T "$@"; }
  exec_ntfy ntfy ntfy user del notifier >/dev/null 2>&1 || true
  exec_ntfy ntfy ntfy user del phone >/dev/null 2>&1 || true
  exec_ntfy -e NTFY_PASSWORD="$NOTIFIER_PW" ntfy ntfy user add notifier >/dev/null
  exec_ntfy -e NTFY_PASSWORD="$PHONE_PW" ntfy ntfy user add phone >/dev/null
  exec_ntfy ntfy ntfy access notifier "$TOPIC" write-only >/dev/null
  exec_ntfy ntfy ntfy access phone "$TOPIC" read-only >/dev/null
  TOKEN=$(exec_ntfy ntfy ntfy token add notifier | grep -o 'tk_[A-Za-z0-9]*')
  python3 - "$TOKEN" "$PHONE_PW" "$IP" "$TOPIC" <<'PY'
import json, sys
from pathlib import Path
token, phone_pw, ip, topic = sys.argv[1:]
p = Path(".secrets/dev.json")
d = json.loads(p.read_text())
d["ntfy"] = {
    "url": "http://localhost:8080",
    "topic": topic,
    "token": token,
    "phone": {"server": f"http://{ip}:8080", "user": "phone", "password": phone_pw},
}
p.write_text(json.dumps(d, indent=2) + "\n")
PY
fi

# A running notifier container read the old token at startup: restart it.
if "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -qx notifier; then
  "${COMPOSE[@]}" restart notifier >/dev/null && echo "restarted the notifier container with the new token"
fi

python3 - <<'PY'
import json
n = json.load(open(".secrets/dev.json"))["ntfy"]
ph = n["phone"]
print(f"""
ntfy is running. On your phone (same Wi-Fi as this computer):
  1. Install the "ntfy" app (Android / iOS)
  2. Add subscription -> topic: {n['topic']}
     -> "Use another server": {ph['server']}
  3. Log in when asked:  user {ph['user']}   password {ph['password']}
Or open {ph['server']} in a browser and log in there.
""")
PY

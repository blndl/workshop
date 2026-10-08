#!/usr/bin/env bash
# Run the whole alarm system in Docker.
#
#   scripts/sim.sh up            # the box + a simulated ESP, short delays, simulator panel on
#                                # ENV_NODE=cpp: env-1 from the C++ edge simulator (ENV_SCENARIO=gas_leak...)
#   scripts/sim.sh hub           # the box only (real ESP, normal 30 s delays, no simulator panel)
#                                # both also start monitoring (Grafana...); NO_MONITORING=1 to skip
#   scripts/sim.sh down          # stop everything (data/ and ntfy accounts are kept)
#   scripts/sim.sh status        # alarm state
#   scripts/sim.sh arm 1234      # arm / disarm with a code
#   scripts/sim.sh disarm 1234
#   scripts/sim.sh verify        # check the event log and the photos
#   scripts/sim.sh probe         # check that the iot network can only reach the broker
#   scripts/sim.sh logs [svc]    # follow the logs (all services, or one)
#   scripts/sim.sh ps            # what is running
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE=(docker compose -f infra/docker/compose.yml)
# Containers run as you, so they can read .secrets/ and write data/ (see compose.yml).
export HOST_UID=$(id -u) HOST_GID=$(id -g)

need_secrets() {
  [[ -f .secrets/dev.json ]] || { echo "no secrets yet: run scripts/dev-secrets.sh first" >&2; exit 1; }
  mkdir -p data models
  [[ -s models/yolov8n.onnx ]] || scripts/get-model.sh || echo "warning: no detector model (scripts/get-model.sh); motion will count without a person check" >&2
}
core() { "${COMPOSE[@]}" exec -T alarm-core python -m alarm_core --broker mosquitto:1883 "$@"; }

# Monitoring (Prometheus, Grafana, Loki) unless NO_MONITORING=1.
MONITORING=(--profile monitoring)
if [[ "${NO_MONITORING:-}" == 1 ]]; then
  MONITORING=()
else
  export GRAFANA_URL="http://127.0.0.1:${GRAFANA_PORT:-3000}"
fi
grafana_password() {
  python3 -c 'import json; print(json.load(open(".secrets/dev.json")).get("grafana", {}).get("admin_password", "admin"))'
}
after_start() {
  # Grafana's read-only database role (databases created before it existed need it too).
  "${COMPOSE[@]}" exec -T postgres psql -q -U alarm -d alarm -v ON_ERROR_STOP=1 < infra/docker/postgres/readonly.sql >/dev/null
  [[ ${#MONITORING[@]} -gt 0 ]] && echo "metrics:    $GRAFANA_URL  (also in the dashboard's Metrics tab; admin password in .secrets/dev.json)"
  return 0
}

case "${1:-help}" in
  up)
    need_secrets
    ENV_PROFILE=() ENV_UP=()
    if [[ "${ENV_NODE:-}" == cpp ]]; then
      ENV_PROFILE=(--profile sim-cpp) ENV_UP=(--scale env-1=0)   # the C++ env-1 replaces the Python one
    else
      "${COMPOSE[@]}" --profile sim-cpp rm -sf env-1-cpp >/dev/null 2>&1 || true
    fi
    GRAFANA_ADMIN_PASSWORD=$(grafana_password) ALARM_SIM=1 EXIT_DELAY=${EXIT_DELAY:-5} ENTRY_DELAY=${ENTRY_DELAY:-10} \
      "${COMPOSE[@]}" --profile hub --profile sim ${ENV_PROFILE[@]+"${ENV_PROFILE[@]}"} ${MONITORING[@]+"${MONITORING[@]}"} \
      up -d --build ${ENV_UP[@]+"${ENV_UP[@]}"}
    echo
    echo "dashboard:  http://127.0.0.1:${API_PORT:-8000}   (simulator panel at the bottom)"
    after_start
    echo "alerts:     http://localhost:8080    (run scripts/dev-ntfy.sh once for the login)"
    ;;
  hub)
    need_secrets
    GRAFANA_ADMIN_PASSWORD=$(grafana_password) "${COMPOSE[@]}" --profile hub ${MONITORING[@]+"${MONITORING[@]}"} up -d --build
    echo "dashboard: http://127.0.0.1:${API_PORT:-8000}"
    after_start
    ;;
  down) "${COMPOSE[@]}" --profile hub --profile sim --profile sim-cpp --profile probe --profile monitoring down ;;
  status) core ctl status ;;
  arm|disarm) core ctl "$1" "${2:?code}" ;;
  verify) core verify-log --snapshots ;;
  probe) "${COMPOSE[@]}" --profile probe run --rm --build probe ;;
  logs) shift; "${COMPOSE[@]}" --profile hub --profile sim --profile sim-cpp --profile monitoring logs -f --tail 50 "$@" ;;
  ps) "${COMPOSE[@]}" --profile hub --profile sim --profile sim-cpp --profile monitoring ps ;;
  *) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac

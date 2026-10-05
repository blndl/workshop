# docker

- `compose.dev.yml`: the dev stack (currently just the Mosquitto broker, on 127.0.0.1:1883). Requires `scripts/dev-secrets.sh` to have run.
- `mosquitto/`: broker config and ACL ([spec section 3](../../protocol/spec.md)). The `attacker` user in `acl` is **dev only**.

The full Pi stack (api, alarm-core, detector, notifier, db, grafana) will be added here.

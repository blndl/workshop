-- Read-only role for Grafana's PostgreSQL panels. Idempotent: run on a fresh
-- database by the image's init, and on every `scripts/sim.sh up` for older ones.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana_ro') THEN
    CREATE ROLE grafana_ro LOGIN PASSWORD 'grafana-ro-dev';   -- dev only
  END IF;
END
$$;
GRANT CONNECT ON DATABASE alarm TO grafana_ro;
GRANT USAGE ON SCHEMA public TO grafana_ro;
GRANT SELECT ON alarm_events TO grafana_ro;

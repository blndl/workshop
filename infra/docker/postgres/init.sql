CREATE TABLE IF NOT EXISTS alarm_events (
    id BIGSERIAL PRIMARY KEY,
    seq BIGINT,                 -- alarm-core's log sequence number (NULL if none)
    event_id TEXT,
    event_type TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One row per log record: the API's backfill and live events can overlap safely.
CREATE UNIQUE INDEX IF NOT EXISTS alarm_events_seq ON alarm_events (seq);

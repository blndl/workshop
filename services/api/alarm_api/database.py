from __future__ import annotations

import os
from datetime import datetime, timezone

import psycopg
from psycopg.types.json import Jsonb


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://alarm:alarm-dev-password@postgres:5432/alarm",
)


def get_connection():
    return psycopg.connect(DATABASE_URL)


def save_event(event: dict) -> None:
    """Persist an alarm event in PostgreSQL."""
    event_time = None

    if "ts" in event:
        event_time = datetime.fromtimestamp(
            float(event["ts"]),
            tz=timezone.utc,
        )

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO alarm_events (
                    event_id,
                    event_type,
                    event_time,
                    event_data
                )
                VALUES (%s, %s, COALESCE(%s, NOW()), %s)
                """,
                (
                    event.get("req"),
                    event["type"],
                    event_time,
                    Jsonb(event),
                ),
            )
"""The web API (task D1): alarm state, recent events, arm/disarm.

No login yet: that is task D2. Until then the server binds to 127.0.0.1 only
and arm/disarm still require a valid alarm code.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Path as PathParam, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .bridge import AlarmCoreTimeout, Bridge

# HTTP status per alarm-core outcome.
OUTCOME_STATUS = {
    "ok": 200,
    "no_change": 200,
    "bad_code": 403,
    "locked": 403,
    "lockout": 403,
    "arm_refused": 409,
}


class CodeIn(BaseModel):
    code: str = Field(pattern=r"^[0-9]{4,8}$", description="Alarm code, 4 to 8 digits")


class SimCommand(BaseModel):
    """A command for a simulated node (see simulator/alarm_sim/control.py)."""

    cmd: Literal["set", "jam", "reboot", "attack"]
    sensor: Literal["door", "pir", "lid"] | None = None
    value: Literal[0, 1] | None = None
    seconds: float | None = Field(None, ge=0.5, le=60)
    name: str | None = Field(None, pattern=r"^[a-z_]{1,24}$")
    args: dict[str, int | str] | None = None


def outcome(events: list[dict]) -> dict:
    """Summarise what alarm-core did with a request."""
    by_type = {e["type"]: e for e in events}
    if "code_lockout" in by_type:
        seconds = by_type["code_lockout"].get("seconds", 0)
        return {"result": "lockout", "detail": f"too many wrong codes, locked for {seconds:g}s"}
    if "code_locked" in by_type:
        return {"result": "locked", "detail": "codes are locked after too many wrong attempts"}
    if "bad_code" in by_type:
        return {"result": "bad_code", "detail": "wrong code"}
    if "arm_refused" in by_type:
        return {"result": "arm_refused", "detail": by_type["arm_refused"].get("problems", [])}
    if "state" in by_type:
        s = by_type["state"]
        out = {"result": "ok", "state": s["state"], "prev": s["prev"]}
        if "delay" in s:
            out["delay"] = s["delay"]
        return out
    return {"result": "no_change"}


def create_app(bridge: Bridge, web_dir: Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        bridge.start()
        yield
        bridge.stop()

    app = FastAPI(
        title="Alarm API",
        version="0.1.0",
        description="State, events and control of the alarm. Login (D2) is not implemented yet.",
        lifespan=lifespan,
    )

    @app.get("/api/health")
    def health():
        age = None if bridge.state_received_at is None else round(time.time() - bridge.state_received_at, 1)
        return {"mqtt_connected": bridge.connected, "state_received": bridge.state is not None, "state_age_s": age}

    @app.get("/api/state")
    def state():
        if bridge.state is None:
            raise HTTPException(503, "no state from alarm-core yet")
        return bridge.state

    @app.get("/api/events")
    def events(
        limit: int = Query(50, ge=1, le=500),
        type: list[str] | None = Query(None, description="only these event types, e.g. ?type=state&type=security"),
    ):
        return bridge.recent_events(limit, set(type) if type else None)

    async def _control(action: str, code: str) -> JSONResponse:
        try:
            events = await bridge.control(action, code, source="api")
        except AlarmCoreTimeout as e:
            raise HTTPException(504, str(e)) from e
        body = outcome(events)
        return JSONResponse(body, status_code=OUTCOME_STATUS[body["result"]])

    @app.post("/api/arm")
    async def arm(body: CodeIn):
        return await _control("arm", body.code)

    @app.post("/api/disarm")
    async def disarm(body: CodeIn):
        return await _control("disarm", body.code)

    @app.get("/api/sim")
    def sim_info():
        """Whether the simulator panel is enabled, and the simulated nodes seen."""
        return {"enabled": bridge.sim, "nodes": bridge.sim_nodes if bridge.sim else {}}

    @app.post("/api/sim/{node}/command", status_code=202)
    def sim_command(cmd: SimCommand, node: str = PathParam(pattern=r"^[a-z0-9-]{1,16}$")):
        if not bridge.sim:
            raise HTTPException(404, "simulator control is disabled (start the API with --sim)")
        bridge.sim_command(node, cmd.model_dump(exclude_none=True))
        return {"sent": True}

    # The React dashboard (web/dist after `npm run build`), served last so /api wins.
    if web_dir and (web_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")

    return app

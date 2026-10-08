"""The web API (task D1): alarm state, recent events, arm/disarm.

No login yet: that is task D2. Until then the server binds to 127.0.0.1 only
and arm/disarm still require a valid alarm code.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Path as PathParam, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .bridge import AlarmCoreTimeout, Bridge
from .metrics import CONTENT_TYPE_LATEST, Metrics

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
    # Any sensor the module describes (the simulated node checks it against its description).
    sensor: str | None = Field(None, pattern=r"^[a-z][a-z0-9_]{0,15}$")
    value: float | None = Field(None, ge=-100_000, le=100_000)  # 0/1 for on/off sensors
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
    if "safety_silenced" in by_type and "state" not in by_type:
        return {"result": "ok", "detail": "safety alarm silenced", "silenced": by_type["safety_silenced"].get("alarms", [])}
    if "arm_refused" in by_type:
        return {"result": "arm_refused", "detail": by_type["arm_refused"].get("problems", [])}
    if "state" in by_type:
        s = by_type["state"]
        out = {"result": "ok", "state": s["state"], "prev": s["prev"]}
        if "delay" in s:
            out["delay"] = s["delay"]
        return out
    return {"result": "no_change"}


def create_app(bridge: Bridge, web_dir: Path | None = None, grafana_url: str | None = None) -> FastAPI:
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
    metrics = Metrics(bridge)

    @app.middleware("http")
    async def time_requests(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        # The route template ("/api/sim/{node}/command"), not the raw path: bounded labels.
        route = getattr(request.scope.get("route"), "path", None) or "other"
        metrics.http.labels(request.method, route, str(response.status_code)).observe(time.perf_counter() - start)
        return response

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics():
        return Response(metrics.render(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/api/info")
    def info():
        """Settings the dashboard needs, e.g. where Grafana is (None if not running)."""
        return {"grafana_url": grafana_url}

    @app.get("/api/health")
    def health():
        age = None if bridge.state_received_at is None else round(time.time() - bridge.state_received_at, 1)
        db = None
        if bridge.store is not None:
            db = {"connected": bridge.store.connected, "pending": bridge.store.pending,
                  "written": bridge.store.written, "dropped": bridge.store.dropped}
        return {"mqtt_connected": bridge.connected, "state_received": bridge.state is not None,
                "state_age_s": age, "database": db}

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
        if not bridge.sim:
            return {"enabled": False, "nodes": {}}
        now = time.time()  # age computed here: the browser's clock may differ from the server's
        return {"enabled": True,
                "nodes": {n: {**st, "age_s": round(now - st.get("received_at", now), 1)} for n, st in bridge.sim_nodes.items()}}

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

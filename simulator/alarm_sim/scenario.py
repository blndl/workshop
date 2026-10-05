"""YAML scenarios: a timeline of sensor changes, attacks and outages.

    name: intrusion
    duration: 12            # seconds
    steps:
      - at: 2
        say: front door opens
        set: {door: 1}
      - at: 5
        attack: replay
        args: {type: EVT, index: 0}
      - at: 6
        jam: 5              # seconds of radio silence
      - at: 8
        reboot: 2           # seconds offline
    expect:                 # checked by `selftest` (in-memory hub)
      hub: [session_started]
      hub_absent: [link_lost]
      node: [auth_fail]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from .attacks import ATTACKS

STEP_ACTIONS = {"set", "attack", "jam", "reboot", "say"}


@dataclass
class Step:
    at: float
    data: dict


@dataclass
class Scenario:
    name: str
    duration: float
    steps: list[Step]
    description: str = ""
    expect: dict[str, list[str]] = field(default_factory=dict)


def load(path: str | Path) -> Scenario:
    raw = yaml.safe_load(Path(path).read_text())
    steps = []
    for i, s in enumerate(raw.get("steps", [])):
        actions = set(s) - {"at", "args"}
        if "at" not in s or not actions or not actions <= STEP_ACTIONS:
            raise ValueError(f"{path}: step {i} needs 'at' and one of {sorted(STEP_ACTIONS)}")
        if "attack" in s and s["attack"] not in ATTACKS:
            raise ValueError(f"{path}: step {i}: unknown attack {s['attack']!r}")
        steps.append(Step(float(s["at"]), s))
    steps.sort(key=lambda st: st.at)
    duration = float(raw.get("duration", (steps[-1].at + 3) if steps else 5))
    expect = raw.get("expect") or {}
    unknown = set(expect) - {"hub", "hub_absent", "node"}
    if unknown:
        raise ValueError(f"{path}: unknown expect keys {sorted(unknown)}")
    return Scenario(raw.get("name", Path(path).stem), duration, steps, raw.get("description", ""), expect)


def run(
    scn: Scenario,
    node,
    attacker,
    tickers: list[Callable[[float], None]],
    now: Callable[[], float],
    sleep: Callable[[float], None],
    log: Callable[[str], None] = print,
    step: float = 0.05,
) -> None:
    """Drive `node` through the scenario. `tickers` run every step (e.g. a hub)."""
    start = now()
    pending = list(scn.steps)
    log(f"=== scenario {scn.name} ({scn.duration:g}s) {scn.description}".rstrip())
    while True:
        t = now()
        elapsed = t - start
        while pending and pending[0].at <= elapsed:
            _apply(pending.pop(0), node, attacker, t, log)
        node.tick(t)
        for tick in tickers:
            tick(t)
        if elapsed >= scn.duration:
            break
        sleep(step)
    log(f"=== end {scn.name}")


def _apply(st: Step, node, attacker, t: float, log) -> None:
    d = st.data
    if "say" in d:
        log(f"--- t={st.at:g}s {d['say']}")
    if "set" in d:
        node.set(t, **d["set"])
    if "jam" in d:
        node.jam(t, float(d["jam"]))
    if "reboot" in d:
        node.reboot(t, float(d["reboot"]))
    if "attack" in d:
        try:
            attacker.run(d["attack"], **(d.get("args") or {}))
        except RuntimeError as e:
            log(f"[attacker] {d['attack']} skipped: {e}")


def check(scn: Scenario, hub_kinds: set[str], node_kinds: set[str]) -> list[str]:
    """Return a list of failed expectations (empty = pass)."""
    failures = []
    for k in scn.expect.get("hub", []):
        if k not in hub_kinds:
            failures.append(f"hub never emitted {k}")
    for k in scn.expect.get("hub_absent", []):
        if k in hub_kinds:
            failures.append(f"hub emitted {k} but should not have")
    for k in scn.expect.get("node", []):
        if k not in node_kinds:
            failures.append(f"node never recorded {k}")
    return failures

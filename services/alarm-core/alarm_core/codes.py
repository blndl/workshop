"""Arm/disarm codes: hashed storage, duress detection, brute-force lockout."""

from __future__ import annotations

import hashlib
import hmac
import os
import re

ITERATIONS = 200_000
_CODE_RE = re.compile(r"[0-9]{4,8}")


def hash_code(code: str, iterations: int = ITERATIONS) -> str:
    if not _CODE_RE.fullmatch(code):
        raise ValueError("code must be 4-8 digits")
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", code.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${h.hex()}"


def verify(code: str, encoded: str) -> bool:
    algo, iterations, salt, expected = encoded.split("$")
    if algo != "pbkdf2_sha256":
        raise ValueError(f"unknown hash {algo}")
    h = hashlib.pbkdf2_hmac("sha256", code.encode(), bytes.fromhex(salt), int(iterations))
    return hmac.compare_digest(h.hex(), expected)


class CodeChecker:
    """check() returns 'user', 'duress', 'bad', 'lockout' (this attempt
    started a lockout) or 'locked'.

    After `max_attempts` bad codes within `window` seconds, every attempt is
    refused for `lockout` seconds, even a correct one.
    """

    def __init__(
        self,
        user: list[str],
        duress: list[str],
        max_attempts: int = 5,
        window: float = 300.0,
        lockout: float = 300.0,
    ):
        self.user, self.duress = user, duress
        self.max_attempts, self.window, self.lockout = max_attempts, window, lockout
        self._failures: list[float] = []
        self.locked_until = float("-inf")

    def check(self, code: str, now: float) -> str:
        if now < self.locked_until:
            return "locked"
        if not isinstance(code, str) or not _CODE_RE.fullmatch(code):
            return self._fail(now)
        # Check every hash so timing doesn't reveal which list matched.
        is_user = any([verify(code, h) for h in self.user])
        is_duress = any([verify(code, h) for h in self.duress])
        if is_duress:
            return "duress"
        if is_user:
            self._failures.clear()
            return "user"
        return self._fail(now)

    def _fail(self, now: float) -> str:
        self._failures = [t for t in self._failures if now - t < self.window] + [now]
        if len(self._failures) >= self.max_attempts:
            self._failures.clear()
            self.locked_until = now + self.lockout
            return "lockout"
        return "bad"

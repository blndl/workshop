"""ntfy backend: one HTTP request per alert, photo attached when there is one."""

from __future__ import annotations

import base64
import urllib.error
import urllib.request

from .rules import Alert


class SendError(Exception):
    def __init__(self, message: str, permanent: bool):
        super().__init__(message)
        self.permanent = permanent


def header(value: str) -> str:
    """HTTP headers are ASCII-only; ntfy decodes RFC 2047 for anything else."""
    if value.isascii() and "\n" not in value:
        return value
    return "=?UTF-8?B?" + base64.b64encode(value.encode()).decode() + "?="


class NtfyBackend:
    def __init__(self, url: str, topic: str, token: str | None = None, timeout: float = 10.0):
        self.endpoint = f"{url.rstrip('/')}/{topic}"
        self.token = token
        self.timeout = timeout

    def send(self, alert: Alert) -> None:
        headers = {"Title": header(alert.title), "Priority": str(alert.priority)}
        if alert.tags:
            headers["Tags"] = ",".join(alert.tags)
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if alert.image and alert.image.exists():
            method, body = "PUT", alert.image.read_bytes()
            headers["Filename"] = alert.image.name
            headers["Message"] = header(alert.message)
        else:
            method, body = "POST", alert.message.encode()
        req = urllib.request.Request(self.endpoint, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp.read()
        except urllib.error.HTTPError as e:
            # 429 and 5xx are worth retrying; other 4xx mean bad config (token, topic).
            raise SendError(f"HTTP {e.code}: {e.read()[:200]!r}", permanent=e.code < 500 and e.code != 429) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise SendError(f"network: {e}", permanent=False) from e

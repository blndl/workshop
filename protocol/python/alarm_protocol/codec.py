"""Reference implementation of alarm protocol v1. See ../../spec.md."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

VERSION = "v1"
MAX_PAYLOAD = 240
MAX_CTR = 2**32 - 1

SIGNED_TYPES = {"HELLO", "WELCOME"}
SEALED_TYPES = {"HB", "EVT", "CMD", "ACK"}
UP_TYPES = {"HELLO", "HB", "EVT", "ACK"}
DOWN_TYPES = {"WELCOME", "CMD"}

_NODE_RE = re.compile(r"[a-z0-9-]{1,16}")
_KEY_RE = re.compile(r"[a-z][a-z0-9_]{0,15}")
_VALUE_RE = re.compile(r"[A-Za-z0-9._-]{1,48}")
_SID_RE = re.compile(r"[0-9a-f]{8}")
_CTR_RE = re.compile(r"0|[1-9][0-9]{0,9}")
_MAC_RE = re.compile(r"[0-9a-f]{32}")


class ProtocolError(Exception):
    """Base class: the message must be dropped."""


class Malformed(ProtocolError):
    pass


class AuthFail(ProtocolError):
    """Bad MAC or tag. Security event."""


class Replay(ProtocolError):
    """Counter not greater than the last accepted one. Security event."""


class UnknownSession(ProtocolError):
    pass


@dataclass(frozen=True)
class Message:
    type: str
    sid: str | None
    ctr: int
    fields: dict[str, str] = field(default_factory=dict)


# --- encoding helpers -------------------------------------------------------


def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64d(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except ValueError as e:
        raise Malformed("bad base64") from e


def encode_fields(fields: dict[str, str]) -> str:
    for k, v in fields.items():
        if not _KEY_RE.fullmatch(k) or not _VALUE_RE.fullmatch(v):
            raise ValueError(f"invalid field {k}={v}")
    return ",".join(f"{k}={v}" for k, v in fields.items())


def parse_fields(text: str) -> dict[str, str]:
    if text == "":
        return {}
    out: dict[str, str] = {}
    for pair in text.split(","):
        k, sep, v = pair.partition("=")
        if not sep or not _KEY_RE.fullmatch(k) or not _VALUE_RE.fullmatch(v):
            raise Malformed(f"bad field {pair!r}")
        if k in out:
            raise Malformed(f"duplicate key {k!r}")
        out[k] = v
    return out


def _check_node(node: str) -> None:
    if not _NODE_RE.fullmatch(node):
        raise ValueError(f"invalid node id {node!r}")


# --- key derivation ---------------------------------------------------------


def hkdf(ikm: bytes, salt: bytes, info: str) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=salt or None, info=info.encode()
    ).derive(ikm)


def hello_key(master: bytes) -> bytes:
    return hkdf(master, b"", "alarm/v1/hello")


@dataclass(frozen=True)
class SessionKeys:
    sid: str
    up: bytes
    down: bytes


def derive_session(master: bytes, node: str, nn: bytes, pn: bytes) -> SessionKeys:
    if len(nn) != 16 or len(pn) != 16:
        raise ValueError("nn and pn must be 16 bytes")
    salt = nn + pn
    return SessionKeys(
        sid=pn[:4].hex(),
        up=hkdf(master, salt, f"alarm/v1/up|{node}"),
        down=hkdf(master, salt, f"alarm/v1/down|{node}"),
    )


# --- framing ----------------------------------------------------------------


def peek(payload: bytes | str) -> tuple[str, list[str]]:
    """Check size/charset/version and split. Returns (type, parts)."""
    if isinstance(payload, bytes):
        if len(payload) > MAX_PAYLOAD:
            raise Malformed("too long")
        try:
            payload = payload.decode("ascii")
        except UnicodeDecodeError as e:
            raise Malformed("not ascii") from e
    if len(payload) > MAX_PAYLOAD or not payload.isascii():
        raise Malformed("too long or not ascii")
    parts = payload.split("|")
    if len(parts) not in (5, 6) or parts[0] != VERSION:
        raise Malformed("bad framing or version")
    mtype = parts[1]
    if mtype in SIGNED_TYPES and len(parts) == 6:
        return mtype, parts
    if mtype in SEALED_TYPES and len(parts) == 5:
        return mtype, parts
    raise Malformed(f"unknown type {mtype!r} or wrong field count")


def _mac(key: bytes, node: str, header_and_body: str) -> str:
    return hmac.new(key, f"{node}|{header_and_body}".encode(), hashlib.sha256).hexdigest()[:32]


def sign(master: bytes, node: str, mtype: str, fields: dict[str, str]) -> str:
    _check_node(node)
    if mtype not in SIGNED_TYPES:
        raise ValueError(f"{mtype} is not a signed type")
    head = f"{VERSION}|{mtype}|-|0|{encode_fields(fields)}"
    out = f"{head}|{_mac(hello_key(master), node, head)}"
    if len(out) > MAX_PAYLOAD:
        raise ValueError("message too long")
    return out


def verify_signed(master: bytes, node: str, payload: bytes | str) -> Message:
    mtype, parts = peek(payload)
    if mtype not in SIGNED_TYPES:
        raise Malformed("not a signed message")
    _, _, sid, ctr, body, mac = parts
    if sid != "-" or ctr != "0" or not _MAC_RE.fullmatch(mac):
        raise Malformed("bad signed header")
    expected = _mac(hello_key(master), node, "|".join(parts[:5]))
    if not hmac.compare_digest(expected, mac):
        raise AuthFail("bad mac")
    return Message(mtype, None, 0, parse_fields(body))


def _nonce(ctr: int) -> bytes:
    return b"\x00\x00\x00\x00" + ctr.to_bytes(8, "big")


def seal(key: bytes, node: str, mtype: str, sid: str, ctr: int, fields: dict[str, str]) -> str:
    _check_node(node)
    if mtype not in SEALED_TYPES:
        raise ValueError(f"{mtype} is not a sealed type")
    if not 1 <= ctr <= MAX_CTR:
        raise ValueError("counter out of range")
    head = f"{VERSION}|{mtype}|{sid}|{ctr}"
    sealed = ChaCha20Poly1305(key).encrypt(
        _nonce(ctr), encode_fields(fields).encode(), f"{node}|{head}".encode()
    )
    out = f"{head}|{b64e(sealed)}"
    if len(out) > MAX_PAYLOAD:
        raise ValueError("message too long")
    return out


def sealed_header(payload: bytes | str) -> tuple[str, str, int, str]:
    """Parse a sealed message header without decrypting: (type, sid, ctr, sealed)."""
    mtype, parts = peek(payload)
    if mtype not in SEALED_TYPES:
        raise Malformed("not a sealed message")
    _, _, sid, ctr, sealed = parts
    if not _SID_RE.fullmatch(sid) or not _CTR_RE.fullmatch(ctr):
        raise Malformed("bad sealed header")
    n = int(ctr)
    if not 1 <= n <= MAX_CTR:
        raise Malformed("counter out of range")
    return mtype, sid, n, sealed


def open_sealed(key: bytes, node: str, payload: bytes | str) -> Message:
    """Decrypt and authenticate. Does NOT check the counter; see Channel."""
    mtype, sid, ctr, sealed = sealed_header(payload)
    raw = b64d(sealed)
    if len(raw) < 16:
        raise Malformed("sealed too short")
    aad = f"{node}|{VERSION}|{mtype}|{sid}|{ctr}".encode()
    try:
        plain = ChaCha20Poly1305(key).decrypt(_nonce(ctr), raw, aad)
    except InvalidTag as e:
        raise AuthFail("bad tag") from e
    try:
        text = plain.decode("ascii")
    except UnicodeDecodeError as e:
        raise Malformed("plaintext not ascii") from e
    return Message(mtype, sid, ctr, parse_fields(text))


# --- session channel --------------------------------------------------------


class Channel:
    """One side of an established session: seals outgoing, opens incoming.

    role="node" sends up / receives down; role="hub" the reverse.
    """

    def __init__(self, keys: SessionKeys, node: str, role: str):
        if role not in ("node", "hub"):
            raise ValueError("role must be 'node' or 'hub'")
        _check_node(node)
        self.keys = keys
        self.node = node
        self.role = role
        self.send_ctr = 0
        self.recv_ctr = 0

    @property
    def _send_key(self) -> bytes:
        return self.keys.up if self.role == "node" else self.keys.down

    @property
    def _recv_key(self) -> bytes:
        return self.keys.down if self.role == "node" else self.keys.up

    @property
    def _recv_types(self) -> set[str]:
        return DOWN_TYPES if self.role == "node" else UP_TYPES

    def seal(self, mtype: str, fields: dict[str, str]) -> str:
        if self.send_ctr >= MAX_CTR:
            raise ProtocolError("counter exhausted, start a new session")
        allowed = UP_TYPES if self.role == "node" else DOWN_TYPES
        if mtype not in allowed:
            raise ValueError(f"{self.role} may not send {mtype}")
        self.send_ctr += 1
        return seal(self._send_key, self.node, mtype, self.keys.sid, self.send_ctr, fields)

    def open(self, payload: bytes | str) -> Message:
        mtype, sid, _, _ = sealed_header(payload)
        if mtype not in self._recv_types:
            raise Malformed(f"{mtype} not allowed in this direction")
        if sid != self.keys.sid:
            raise UnknownSession(sid)
        msg = open_sealed(self._recv_key, self.node, payload)
        if msg.ctr <= self.recv_ctr:
            raise Replay(f"ctr {msg.ctr} <= {self.recv_ctr}")
        self.recv_ctr = msg.ctr
        return msg

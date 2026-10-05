"""Message transports: a real MQTT client, and an in-memory bus for tests."""

from __future__ import annotations

from typing import Callable

Handler = Callable[[str, bytes], None]  # (topic, payload)


def topic_matches(pattern: str, topic: str) -> bool:
    """MQTT wildcard matching for '+' and a trailing '#'."""
    p, t = pattern.split("/"), topic.split("/")
    for i, part in enumerate(p):
        if part == "#":
            return True
        if i >= len(t) or (part != "+" and part != t[i]):
            return False
    return len(p) == len(t)


class MemoryBus:
    """Synchronous in-process broker. Delivery happens inside publish()."""

    def __init__(self):
        self._subs: list[tuple[str, Handler]] = []
        self.log: list[tuple[str, str]] = []

    def client(self) -> "MemoryTransport":
        return MemoryTransport(self)

    def _publish(self, topic: str, payload: bytes) -> None:
        self.log.append((topic, payload.decode("ascii", "replace")))
        for pattern, handler in list(self._subs):
            if topic_matches(pattern, topic):
                handler(topic, payload)


class MemoryTransport:
    def __init__(self, bus: MemoryBus):
        self._bus = bus

    def connect(self, on_connect: Callable[[], None] | None = None) -> None:
        if on_connect:
            on_connect()

    def subscribe(self, pattern: str, handler: Handler) -> None:
        self._bus._subs.append((pattern, handler))

    def publish(self, topic: str, payload: str | bytes, retain: bool = False) -> None:
        self._bus._publish(topic, payload.encode() if isinstance(payload, str) else payload)

    def close(self) -> None:
        pass


class MqttTransport:
    """paho-mqtt client. Callbacks run on paho's network thread."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        client_id: str,
        will: tuple[str, str] | None = None,
        keepalive: int = 5,
    ):
        import paho.mqtt.client as mqtt

        self._mqtt = mqtt
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        self._client.username_pw_set(username, password)
        if will:
            self._client.will_set(will[0], will[1], qos=0, retain=True)
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._host, self._port, self._keepalive = host, port, keepalive
        self._subs: list[tuple[str, Handler]] = []
        self._on_connect: Callable[[], None] | None = None
        self._client.on_connect = self._handle_connect
        self._client.on_message = self._handle_message

    def connect(self, on_connect: Callable[[], None] | None = None) -> None:
        self._on_connect = on_connect
        self._client.connect(self._host, self._port, self._keepalive)
        self._client.loop_start()

    def _handle_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            print(f"[mqtt] connect refused: {reason_code}")
            return
        for pattern, _ in self._subs:
            client.subscribe(pattern, qos=0)
        if self._on_connect:
            self._on_connect()

    def _handle_message(self, client, userdata, msg) -> None:
        for pattern, handler in self._subs:
            if topic_matches(pattern, msg.topic):
                handler(msg.topic, msg.payload)

    def subscribe(self, pattern: str, handler: Handler) -> None:
        self._subs.append((pattern, handler))
        if self._client.is_connected():
            self._client.subscribe(pattern, qos=0)

    def publish(self, topic: str, payload: str | bytes, retain: bool = False) -> None:
        self._client.publish(topic, payload, qos=0, retain=retain)

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

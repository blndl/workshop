# protocol

The contract between sensor nodes (ESP8266) and the hub (Pi): MQTT over Wi-Fi, with every message encrypted and authenticated (ChaCha20-Poly1305) and a session handshake that blocks replays.

- [`spec.md`](spec.md): the specification, the source of truth
- [`test-vectors.json`](test-vectors.json): exact expected outputs, for checking the firmware
- [`python/`](python/): reference codec, used by the simulator and alarm-core

From the repo root:

```bash
python3 -m venv .venv && .venv/bin/pip install -e protocol/python -e 'simulator[dev]'
.venv/bin/pytest protocol/python
(cd protocol/python && ../../.venv/bin/python gen_vectors.py)   # after changing the codec
```

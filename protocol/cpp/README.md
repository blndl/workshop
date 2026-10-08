# protocol/cpp

[Protocol v1](../spec.md) in C++17, for the C++ edge simulator now and the ESP firmware later. It follows the same rules as the Python codec and is tested against the same [`test-vectors.json`](../test-vectors.json), **byte for byte**: same keys, same handshake, same sealed messages, and the same rejections (tampering, replay, wrong key, wrong module, wrong direction, malformed input).

```cpp
#include <alarm/protocol.hpp>
using namespace alarmproto;   // not "alarm": that name clashes with POSIX alarm()

std::string hello = sign(master, "env-1", "HELLO", {{"fw", "1.0"}, {"nn", b64e(nn)}});
// ... after WELCOME:
Channel ch(deriveSession(master, "env-1", nn, pn), "env-1", Channel::Role::Node);
std::string hb = ch.seal("HB", {{"gas", "121.4"}, {"temp", "21.1"}});
Message cmd = ch.open(payload);   // throws ProtocolError{AuthFail | Replay | UnknownSession | Malformed}
```

| File | Contents |
|---|---|
| `include/alarm/protocol.hpp` | The API: fields, keys (HKDF), handshake (HMAC), sealed messages (ChaCha20-Poly1305), `Channel` with replay protection |
| `src/protocol.cpp` | Implementation on OpenSSL's libcrypto |
| `tests/test_protocol.cpp` | Reproduces `test-vectors.json` and checks every rejection |

## Build and test

Needs CMake, a C++17 compiler, OpenSSL (`libssl-dev`) and nlohmann-json (tests only). Without them, use Docker:

```bash
docker build -f protocol/cpp/Dockerfile.test protocol      # builds and runs the tests
```

Natively:

```bash
cmake -S protocol/cpp -B build -DBUILD_TESTING=ON && cmake --build build && ctest --test-dir build --output-on-failure
```

Other CMake projects use it with `add_subdirectory(path/to/protocol/cpp)` and link `alarm_protocol`, as [IA_VISON/edge-simulator](../../IA_VISON/edge-simulator) does.

## For the ESP8266 firmware

The functions map one to one onto what the ESP8266 Arduino core ships in **BearSSL**: `br_hmac`, `br_hkdf`, `br_chacha20_ct_run` + `br_poly1305_ctmul_run`. Only `src/protocol.cpp`'s crypto calls need swapping; the framing, fields and `Channel` logic stay. Keep the test vectors as the acceptance test.

When the protocol changes, regenerate the vectors from Python (`protocol/python/gen_vectors.py`) and both implementations must pass.

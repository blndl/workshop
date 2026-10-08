# firmware

ESP8266 firmware (to do). Start from [`protocol/cpp`](../protocol/cpp): the protocol is already written and tested in C++17 against `protocol/test-vectors.json`. On the ESP, swap its OpenSSL calls for BearSSL (shipped with the ESP8266 Arduino core), and reuse the session logic from [`IA_VISON/edge-simulator/src/alarm/AlarmNode.cpp`](../IA_VISON/edge-simulator/src/alarm/AlarmNode.cpp) (handshake, heartbeats, commands, downlink watchdog). The sensor names and roles come from [`config/modules.yaml`](../config/modules.yaml).

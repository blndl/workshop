// Alarm protocol v1 in C++17 (namespace alarmproto: plain "alarm" clashes with POSIX alarm()): the same rules as protocol/python/alarm_protocol/codec.py
// (spec: protocol/spec.md). Checked against protocol/test-vectors.json, byte for byte.
//
// Crypto comes from OpenSSL (libcrypto): HMAC-SHA256, HKDF-SHA256, ChaCha20-Poly1305.
// The ESP8266 firmware will use the same functions from BearSSL.
#pragma once

#include <cstdint>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace alarmproto {

using Bytes = std::vector<std::uint8_t>;
using Fields = std::vector<std::pair<std::string, std::string>>;  // order is kept on the wire

constexpr const char* kVersion = "v1";
constexpr std::size_t kMaxPayload = 240;
constexpr std::uint64_t kMaxCounter = 0xFFFFFFFFull;

// Why a message was dropped. AuthFail and Replay are security events.
class ProtocolError : public std::runtime_error {
 public:
  enum class Kind { Malformed, AuthFail, Replay, UnknownSession };
  ProtocolError(Kind kind, const std::string& what) : std::runtime_error(what), kind(kind) {}
  Kind kind;
};

struct Message {
  std::string type;
  std::string sid;          // empty for signed (handshake) messages
  std::uint64_t ctr = 0;
  Fields fields;

  const std::string* get(const std::string& key) const;
};

// --- encoding --------------------------------------------------------------
std::string b64e(const Bytes& data);  // base64url, no padding
Bytes b64d(const std::string& text);  // throws Malformed
std::string hex(const Bytes& data);
Bytes unhex(const std::string& text);
std::string encodeFields(const Fields& fields);
Fields parseFields(const std::string& text);  // throws Malformed

// --- keys ------------------------------------------------------------------
Bytes hkdf(const Bytes& ikm, const Bytes& salt, const std::string& info, std::size_t length = 32);
Bytes helloKey(const Bytes& master);

struct SessionKeys {
  std::string sid;  // hex of pn[0:4]
  Bytes up;         // node -> hub
  Bytes down;       // hub -> node
};
SessionKeys deriveSession(const Bytes& master, const std::string& node, const Bytes& nn, const Bytes& pn);
Bytes randomBytes(std::size_t n);

// --- messages --------------------------------------------------------------
// Handshake: HELLO / WELCOME, HMAC-signed, in clear.
std::string sign(const Bytes& master, const std::string& node, const std::string& type, const Fields& fields);
Message verifySigned(const Bytes& master, const std::string& node, const std::string& payload);

// Everything else: ChaCha20-Poly1305, header authenticated as AAD.
std::string seal(const Bytes& key, const std::string& node, const std::string& type, const std::string& sid,
                 std::uint64_t ctr, const Fields& fields);
Message openSealed(const Bytes& key, const std::string& node, const std::string& payload);  // no counter check

// Size, charset, version, framing; returns the type.
std::string peekType(const std::string& payload);

// One side of a session: seals what it sends, opens what it receives, refuses replays.
class Channel {
 public:
  enum class Role { Node, Hub };
  Channel(SessionKeys keys, std::string node, Role role);
  std::string seal(const std::string& type, const Fields& fields);
  Message open(const std::string& payload);
  const SessionKeys& keys() const { return keys_; }
  std::uint64_t sendCounter() const { return send_; }
  std::uint64_t receiveCounter() const { return recv_; }

 private:
  SessionKeys keys_;
  std::string node_;
  Role role_;
  std::uint64_t send_ = 0;
  std::uint64_t recv_ = 0;
};

}  // namespace alarmproto

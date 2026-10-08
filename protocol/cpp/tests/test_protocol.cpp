// The C++ protocol must produce exactly protocol/test-vectors.json (made by the Python codec),
// and reject what the Python one rejects.
#include "alarm/protocol.hpp"

#include <nlohmann/json.hpp>

#include <fstream>
#include <functional>
#include <iostream>

using namespace alarmproto;
using Kind = ProtocolError::Kind;

static int failures = 0, checks = 0;

#define CHECK(cond)                                                              \
  do {                                                                           \
    ++checks;                                                                    \
    if (!(cond)) {                                                               \
      ++failures;                                                                \
      std::cerr << "FAIL " << __FILE__ << ":" << __LINE__ << "  " #cond "\n";  \
    }                                                                            \
  } while (0)

static bool rejects(Kind kind, const std::function<void()>& f) {
  try {
    f();
  } catch (const ProtocolError& e) {
    return e.kind == kind;
  }
  return false;
}

static Fields fieldsFrom(const std::string& plaintext) { return parseFields(plaintext); }

int main(int argc, char** argv) {
  const std::string path = argc > 1 ? argv[1] : "../test-vectors.json";
  std::ifstream in(path);
  if (!in) {
    std::cerr << "cannot open " << path << "\n";
    return 2;
  }
  auto v = nlohmann::json::parse(in);
  const Bytes master = unhex(v["inputs"]["master_hex"]);
  const std::string node = v["inputs"]["node"];
  const Bytes nn = unhex(v["inputs"]["nn_hex"]), pn = unhex(v["inputs"]["pn_hex"]);
  const auto& msgs = v["messages"];

  // Keys
  CHECK(hex(helloKey(master)) == v["derived"]["k_hello_hex"]);
  SessionKeys keys = deriveSession(master, node, nn, pn);
  CHECK(keys.sid == v["derived"]["sid"]);
  CHECK(hex(keys.up) == v["derived"]["k_up_hex"]);
  CHECK(hex(keys.down) == v["derived"]["k_down_hex"]);

  // Handshake, byte for byte
  CHECK(sign(master, node, "HELLO", {{"fw", "0.1.0"}, {"nn", b64e(nn)}}) == msgs[0]["payload"]);
  CHECK(sign(master, node, "WELCOME", {{"nn", b64e(nn)}, {"pn", b64e(pn)}}) == msgs[1]["payload"]);
  Message hello = verifySigned(master, node, msgs[0]["payload"]);
  CHECK(hello.type == "HELLO" && *hello.get("nn") == b64e(nn) && b64d(*hello.get("nn")) == nn);

  // Session: the same sequence as gen_vectors.py
  Channel nodeSide(keys, node, Channel::Role::Node), hubSide(keys, node, Channel::Role::Hub);
  CHECK(nodeSide.seal("HB", fieldsFrom(msgs[2]["plaintext"])) == msgs[2]["payload"]);
  CHECK(nodeSide.seal("EVT", fieldsFrom(msgs[3]["plaintext"])) == msgs[3]["payload"]);
  CHECK(hubSide.seal("CMD", fieldsFrom(msgs[4]["plaintext"])) == msgs[4]["payload"]);
  CHECK(nodeSide.seal("ACK", fieldsFrom(msgs[5]["plaintext"])) == msgs[5]["payload"]);

  // And opens what Python sealed
  Channel hubRx(keys, node, Channel::Role::Hub), nodeRx(keys, node, Channel::Role::Node);
  Message hb = hubRx.open(msgs[2]["payload"]);
  CHECK(hb.type == "HB" && hb.ctr == 1 && encodeFields(hb.fields) == msgs[2]["plaintext"]);
  Message cmd = nodeRx.open(msgs[4]["payload"]);
  CHECK(cmd.type == "CMD" && *cmd.get("buzzer") == "1");

  // Rejections
  const std::string evt = msgs[3]["payload"];
  CHECK(!rejects(Kind::Replay, [&] { hubRx.open(evt); }));                // ctr 2 > 1: accepted
  CHECK(rejects(Kind::Replay, [&] { hubRx.open(evt); }));                 // the same again: replay
  CHECK(rejects(Kind::Replay, [&] { hubRx.open(msgs[2]["payload"]); }));  // older counter
  std::string tampered = evt;
  tampered.replace(tampered.find("|EVT|"), 5, "|HB|");
  CHECK(rejects(Kind::AuthFail, [&] { openSealed(keys.up, node, tampered); }));
  CHECK(rejects(Kind::AuthFail, [&] { openSealed(keys.up, "door-2", evt); }));  // moved to another module
  CHECK(rejects(Kind::AuthFail, [&] { openSealed(Bytes(32, 7), node, evt); }));  // wrong key
  CHECK(rejects(Kind::AuthFail, [&] { verifySigned(Bytes(32, 1), node, msgs[0]["payload"]); }));
  CHECK(rejects(Kind::UnknownSession, [&] { Channel(deriveSession(master, node, nn, Bytes(16, 9)), node, Channel::Role::Hub).open(evt); }));
  CHECK(rejects(Kind::Malformed, [&] { hubRx.open("v1|CMD|10111213|9|AAAA"); }));  // hub never accepts CMD
  CHECK(rejects(Kind::Malformed, [&] { peekType(std::string(241, 'x')); }));
  CHECK(rejects(Kind::Malformed, [&] { peekType("v2|HB|00000000|1|AAAA"); }));
  CHECK(rejects(Kind::Malformed, [&] { openSealed(keys.up, node, "v1|HB|10111213|01|AAAA"); }));
  CHECK(rejects(Kind::Malformed, [&] { parseFields("a=1,a=2"); }));
  CHECK(rejects(Kind::Malformed, [&] { parseFields("A=1"); }));

  // Encoding round trips
  for (std::size_t n = 0; n < 40; ++n) {
    Bytes b = randomBytes(n);
    CHECK(b64d(b64e(b)) == b);
  }

  std::cout << checks - failures << "/" << checks << " checks passed\n";
  return failures ? 1 : 0;
}

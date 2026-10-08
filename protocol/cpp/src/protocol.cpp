#include "alarm/protocol.hpp"

#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/hmac.h>
#include <openssl/kdf.h>
#include <openssl/rand.h>

#include <algorithm>
#include <cctype>
#include <memory>
#include <regex>
#include <set>
#include <sstream>

namespace alarmproto {
namespace {

using Kind = ProtocolError::Kind;

const std::set<std::string> kSigned = {"HELLO", "WELCOME"};
const std::set<std::string> kSealed = {"HB", "EVT", "CMD", "ACK"};
const std::set<std::string> kUp = {"HELLO", "HB", "EVT", "ACK"};
const std::set<std::string> kDown = {"WELCOME", "CMD"};

const std::regex kNodeRe("[a-z0-9-]{1,16}");
const std::regex kKeyRe("[a-z][a-z0-9_]{0,15}");
const std::regex kValueRe("[A-Za-z0-9._-]{1,48}");
const std::regex kSidRe("[0-9a-f]{8}");
const std::regex kCtrRe("0|[1-9][0-9]{0,9}");
const std::regex kMacRe("[0-9a-f]{32}");

[[noreturn]] void fail(Kind kind, const std::string& what) { throw ProtocolError(kind, what); }

std::vector<std::string> split(const std::string& s, char sep) {
  std::vector<std::string> out;
  std::string cur;
  for (char c : s) {
    if (c == sep) {
      out.push_back(cur);
      cur.clear();
    } else {
      cur += c;
    }
  }
  out.push_back(cur);
  return out;
}

void checkNode(const std::string& node) {
  if (!std::regex_match(node, kNodeRe)) throw std::invalid_argument("invalid node id: " + node);
}

std::string hmac32(const Bytes& key, const std::string& data) {
  unsigned char out[EVP_MAX_MD_SIZE];
  unsigned int len = 0;
  if (!HMAC(EVP_sha256(), key.data(), static_cast<int>(key.size()),
            reinterpret_cast<const unsigned char*>(data.data()), data.size(), out, &len))
    throw std::runtime_error("HMAC failed");
  return hex(Bytes(out, out + len)).substr(0, 32);  // first 16 bytes, as hex
}

Bytes nonceFor(std::uint64_t ctr) {
  Bytes n(12, 0);
  for (int i = 0; i < 8; ++i) n[4 + i] = static_cast<std::uint8_t>(ctr >> (56 - 8 * i));
  return n;
}

struct CipherCtx {
  EVP_CIPHER_CTX* p = EVP_CIPHER_CTX_new();
  ~CipherCtx() { EVP_CIPHER_CTX_free(p); }
};

Bytes aeadSeal(const Bytes& key, const Bytes& nonce, const std::string& plain, const std::string& aad) {
  CipherCtx ctx;
  int len = 0;
  Bytes out(plain.size() + 16);
  if (!EVP_EncryptInit_ex(ctx.p, EVP_chacha20_poly1305(), nullptr, nullptr, nullptr) ||
      !EVP_CIPHER_CTX_ctrl(ctx.p, EVP_CTRL_AEAD_SET_IVLEN, 12, nullptr) ||
      !EVP_EncryptInit_ex(ctx.p, nullptr, nullptr, key.data(), nonce.data()) ||
      !EVP_EncryptUpdate(ctx.p, nullptr, &len, reinterpret_cast<const unsigned char*>(aad.data()), static_cast<int>(aad.size())) ||
      !EVP_EncryptUpdate(ctx.p, out.data(), &len, reinterpret_cast<const unsigned char*>(plain.data()), static_cast<int>(plain.size())) ||
      !EVP_EncryptFinal_ex(ctx.p, out.data() + len, &len) ||
      !EVP_CIPHER_CTX_ctrl(ctx.p, EVP_CTRL_AEAD_GET_TAG, 16, out.data() + plain.size()))
    throw std::runtime_error("ChaCha20-Poly1305 encryption failed");
  return out;
}

std::string aeadOpen(const Bytes& key, const Bytes& nonce, const Bytes& sealed, const std::string& aad) {
  if (sealed.size() < 16) fail(Kind::Malformed, "sealed too short");
  const std::size_t n = sealed.size() - 16;
  CipherCtx ctx;
  int len = 0;
  Bytes out(n + 1);
  Bytes tag(sealed.end() - 16, sealed.end());
  bool ok = EVP_DecryptInit_ex(ctx.p, EVP_chacha20_poly1305(), nullptr, nullptr, nullptr) &&
            EVP_CIPHER_CTX_ctrl(ctx.p, EVP_CTRL_AEAD_SET_IVLEN, 12, nullptr) &&
            EVP_DecryptInit_ex(ctx.p, nullptr, nullptr, key.data(), nonce.data()) &&
            EVP_DecryptUpdate(ctx.p, nullptr, &len, reinterpret_cast<const unsigned char*>(aad.data()), static_cast<int>(aad.size())) &&
            EVP_DecryptUpdate(ctx.p, out.data(), &len, sealed.data(), static_cast<int>(n)) &&
            EVP_CIPHER_CTX_ctrl(ctx.p, EVP_CTRL_AEAD_SET_TAG, 16, tag.data());
  int final_len = 0;
  if (!ok || EVP_DecryptFinal_ex(ctx.p, out.data() + len, &final_len) <= 0) fail(Kind::AuthFail, "bad tag");
  return std::string(out.begin(), out.begin() + static_cast<long>(n));
}

std::uint64_t parseCtr(const std::string& s) {
  if (!std::regex_match(s, kCtrRe)) fail(Kind::Malformed, "bad counter");
  return std::stoull(s);
}

}  // namespace

const std::string* Message::get(const std::string& key) const {
  for (const auto& [k, v] : fields)
    if (k == key) return &v;
  return nullptr;
}

// --- encoding --------------------------------------------------------------

std::string b64e(const Bytes& data) {
  static const char* a = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
  std::string out;
  std::size_t i = 0;
  for (; i + 2 < data.size(); i += 3) {
    std::uint32_t v = (data[i] << 16) | (data[i + 1] << 8) | data[i + 2];
    out += a[(v >> 18) & 63], out += a[(v >> 12) & 63], out += a[(v >> 6) & 63], out += a[v & 63];
  }
  if (data.size() - i == 1) {
    std::uint32_t v = data[i] << 16;
    out += a[(v >> 18) & 63], out += a[(v >> 12) & 63];
  } else if (data.size() - i == 2) {
    std::uint32_t v = (data[i] << 16) | (data[i + 1] << 8);
    out += a[(v >> 18) & 63], out += a[(v >> 12) & 63], out += a[(v >> 6) & 63];
  }
  return out;
}

Bytes b64d(const std::string& text) {
  auto val = [](char c) -> int {
    if (c >= 'A' && c <= 'Z') return c - 'A';
    if (c >= 'a' && c <= 'z') return c - 'a' + 26;
    if (c >= '0' && c <= '9') return c - '0' + 52;
    if (c == '-') return 62;
    if (c == '_') return 63;
    return -1;
  };
  if (text.size() % 4 == 1) fail(Kind::Malformed, "bad base64");
  Bytes out;
  std::uint32_t buf = 0;
  int bits = 0;
  for (char c : text) {
    int v = val(c);
    if (v < 0) fail(Kind::Malformed, "bad base64");
    buf = (buf << 6) | static_cast<std::uint32_t>(v);
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out.push_back(static_cast<std::uint8_t>((buf >> bits) & 0xFF));
    }
  }
  return out;
}

std::string hex(const Bytes& data) {
  static const char* d = "0123456789abcdef";
  std::string out;
  for (auto b : data) out += d[b >> 4], out += d[b & 15];
  return out;
}

Bytes unhex(const std::string& text) {
  if (text.size() % 2) throw std::invalid_argument("odd hex length");
  Bytes out;
  for (std::size_t i = 0; i < text.size(); i += 2) out.push_back(static_cast<std::uint8_t>(std::stoi(text.substr(i, 2), nullptr, 16)));
  return out;
}

std::string encodeFields(const Fields& fields) {
  std::string out;
  for (const auto& [k, v] : fields) {
    if (!std::regex_match(k, kKeyRe) || !std::regex_match(v, kValueRe))
      throw std::invalid_argument("invalid field " + k + "=" + v);
    if (!out.empty()) out += ',';
    out += k + "=" + v;
  }
  return out;
}

Fields parseFields(const std::string& text) {
  Fields out;
  if (text.empty()) return out;
  std::set<std::string> seen;
  for (const auto& pair : split(text, ',')) {
    auto eq = pair.find('=');
    if (eq == std::string::npos) fail(Kind::Malformed, "bad field " + pair);
    std::string k = pair.substr(0, eq), v = pair.substr(eq + 1);
    if (!std::regex_match(k, kKeyRe) || !std::regex_match(v, kValueRe)) fail(Kind::Malformed, "bad field " + pair);
    if (!seen.insert(k).second) fail(Kind::Malformed, "duplicate key " + k);
    out.emplace_back(k, v);
  }
  return out;
}

// --- keys ------------------------------------------------------------------

Bytes hkdf(const Bytes& ikm, const Bytes& salt, const std::string& info, std::size_t length) {
  std::unique_ptr<EVP_PKEY_CTX, decltype(&EVP_PKEY_CTX_free)> ctx(EVP_PKEY_CTX_new_id(EVP_PKEY_HKDF, nullptr), EVP_PKEY_CTX_free);
  Bytes out(length);
  std::size_t len = length;
  // No salt = HashLen zero bytes (RFC 5869), which is what an empty HMAC key amounts to.
  Bytes s = salt.empty() ? Bytes(32, 0) : salt;
  if (!ctx || EVP_PKEY_derive_init(ctx.get()) <= 0 || EVP_PKEY_CTX_set_hkdf_md(ctx.get(), EVP_sha256()) <= 0 ||
      EVP_PKEY_CTX_set1_hkdf_salt(ctx.get(), s.data(), static_cast<int>(s.size())) <= 0 ||
      EVP_PKEY_CTX_set1_hkdf_key(ctx.get(), ikm.data(), static_cast<int>(ikm.size())) <= 0 ||
      EVP_PKEY_CTX_add1_hkdf_info(ctx.get(), reinterpret_cast<const unsigned char*>(info.data()), static_cast<int>(info.size())) <= 0 ||
      EVP_PKEY_derive(ctx.get(), out.data(), &len) <= 0)
    throw std::runtime_error("HKDF failed");
  return out;
}

Bytes helloKey(const Bytes& master) { return hkdf(master, {}, "alarm/v1/hello"); }

SessionKeys deriveSession(const Bytes& master, const std::string& node, const Bytes& nn, const Bytes& pn) {
  if (nn.size() != 16 || pn.size() != 16) throw std::invalid_argument("nn and pn must be 16 bytes");
  Bytes salt = nn;
  salt.insert(salt.end(), pn.begin(), pn.end());
  return {hex(Bytes(pn.begin(), pn.begin() + 4)), hkdf(master, salt, "alarm/v1/up|" + node),
          hkdf(master, salt, "alarm/v1/down|" + node)};
}

Bytes randomBytes(std::size_t n) {
  Bytes out(n);
  if (RAND_bytes(out.data(), static_cast<int>(n)) != 1) throw std::runtime_error("RAND_bytes failed");
  return out;
}

// --- messages --------------------------------------------------------------

std::string peekType(const std::string& payload) {
  if (payload.size() > kMaxPayload) fail(Kind::Malformed, "too long");
  if (!std::all_of(payload.begin(), payload.end(), [](unsigned char c) { return c < 128; })) fail(Kind::Malformed, "not ascii");
  auto parts = split(payload, '|');
  if ((parts.size() != 5 && parts.size() != 6) || parts[0] != kVersion) fail(Kind::Malformed, "bad framing or version");
  const std::string& t = parts[1];
  if ((kSigned.count(t) && parts.size() == 6) || (kSealed.count(t) && parts.size() == 5)) return t;
  fail(Kind::Malformed, "unknown type " + t + " or wrong field count");
}

std::string sign(const Bytes& master, const std::string& node, const std::string& type, const Fields& fields) {
  checkNode(node);
  if (!kSigned.count(type)) throw std::invalid_argument(type + " is not a signed type");
  std::string head = std::string(kVersion) + "|" + type + "|-|0|" + encodeFields(fields);
  std::string out = head + "|" + hmac32(helloKey(master), node + "|" + head);
  if (out.size() > kMaxPayload) throw std::invalid_argument("message too long");
  return out;
}

Message verifySigned(const Bytes& master, const std::string& node, const std::string& payload) {
  std::string type = peekType(payload);
  if (!kSigned.count(type)) fail(Kind::Malformed, "not a signed message");
  auto p = split(payload, '|');
  if (p[2] != "-" || p[3] != "0" || !std::regex_match(p[5], kMacRe)) fail(Kind::Malformed, "bad signed header");
  std::string expected = hmac32(helloKey(master), node + "|" + p[0] + "|" + p[1] + "|" + p[2] + "|" + p[3] + "|" + p[4]);
  if (CRYPTO_memcmp(expected.data(), p[5].data(), 32) != 0) fail(Kind::AuthFail, "bad mac");
  return {type, "", 0, parseFields(p[4])};
}

std::string seal(const Bytes& key, const std::string& node, const std::string& type, const std::string& sid,
                 std::uint64_t ctr, const Fields& fields) {
  checkNode(node);
  if (!kSealed.count(type)) throw std::invalid_argument(type + " is not a sealed type");
  if (ctr < 1 || ctr > kMaxCounter) throw std::invalid_argument("counter out of range");
  std::string head = std::string(kVersion) + "|" + type + "|" + sid + "|" + std::to_string(ctr);
  std::string out = head + "|" + b64e(aeadSeal(key, nonceFor(ctr), encodeFields(fields), node + "|" + head));
  if (out.size() > kMaxPayload) throw std::invalid_argument("message too long");
  return out;
}

Message openSealed(const Bytes& key, const std::string& node, const std::string& payload) {
  std::string type = peekType(payload);
  if (!kSealed.count(type)) fail(Kind::Malformed, "not a sealed message");
  auto p = split(payload, '|');
  if (!std::regex_match(p[2], kSidRe)) fail(Kind::Malformed, "bad sealed header");
  std::uint64_t ctr = parseCtr(p[3]);
  if (ctr < 1 || ctr > kMaxCounter) fail(Kind::Malformed, "counter out of range");
  std::string plain = aeadOpen(key, nonceFor(ctr), b64d(p[4]), node + "|" + p[0] + "|" + p[1] + "|" + p[2] + "|" + p[3]);
  if (!std::all_of(plain.begin(), plain.end(), [](unsigned char c) { return c < 128; })) fail(Kind::Malformed, "plaintext not ascii");
  return {type, p[2], ctr, parseFields(plain)};
}

Channel::Channel(SessionKeys keys, std::string node, Role role) : keys_(std::move(keys)), node_(std::move(node)), role_(role) {
  checkNode(node_);
}

std::string Channel::seal(const std::string& type, const Fields& fields) {
  const auto& allowed = role_ == Role::Node ? kUp : kDown;
  if (!allowed.count(type)) throw std::invalid_argument("this side may not send " + type);
  if (send_ >= kMaxCounter) throw ProtocolError(Kind::Malformed, "counter exhausted, start a new session");
  ++send_;
  return alarmproto::seal(role_ == Role::Node ? keys_.up : keys_.down, node_, type, keys_.sid, send_, fields);
}

Message Channel::open(const std::string& payload) {
  std::string type = peekType(payload);
  const auto& allowed = role_ == Role::Node ? kDown : kUp;
  if (!kSealed.count(type) || !allowed.count(type)) fail(Kind::Malformed, type + " not allowed in this direction");
  auto p = split(payload, '|');
  if (p[2] != keys_.sid) fail(Kind::UnknownSession, p[2]);
  Message m = openSealed(role_ == Role::Node ? keys_.down : keys_.up, node_, payload);
  if (m.ctr <= recv_) fail(Kind::Replay, "ctr " + std::to_string(m.ctr) + " <= " + std::to_string(recv_));
  recv_ = m.ctr;
  return m;
}

}  // namespace alarmproto

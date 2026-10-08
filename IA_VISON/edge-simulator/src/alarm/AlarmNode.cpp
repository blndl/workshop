#include "AlarmNode.h"

#include <mosquitto.h>
#include <nlohmann/json.hpp>

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>

namespace {

constexpr double kHbInterval = 1.0;
constexpr double kHelloRetry = 2.0;
constexpr double kDownlinkTimeout = 10.0;

std::string env(const char* name, const std::string& fallback) {
  const char* v = std::getenv(name);
  return v && *v ? v : fallback;
}

std::string fmt(double v) {
  char buf[32];
  std::snprintf(buf, sizeof buf, "%.1f", v);
  return buf;
}

std::string upTopic(const std::string& n) { return "alarm/v1/" + n + "/up"; }
std::string downTopic(const std::string& n) { return "alarm/v1/" + n + "/down"; }
std::string statusTopic(const std::string& n) { return "alarm/v1/" + n + "/status"; }

}  // namespace

AlarmNodeConfig loadConfig() {
  AlarmNodeConfig c;
  c.nodeId = env("NODE_ID", c.nodeId);
  c.scenario = env("SCENARIO", c.scenario);
  const std::string path = env("SECRETS", "/app/.secrets/dev.json");
  std::ifstream in(path);
  if (!in) throw std::runtime_error("cannot read " + path + " (run scripts/dev-secrets.sh)");
  auto s = nlohmann::json::parse(in);
  if (!s["nodes"].contains(c.nodeId)) throw std::runtime_error("no key for " + c.nodeId + " in " + path);
  c.key = alarmproto::unhex(s["nodes"][c.nodeId]["key"].get<std::string>());
  c.password = s["nodes"][c.nodeId]["password"].get<std::string>();
  c.host = env("MQTT_HOST", s.value("/broker/host"_json_pointer, std::string("127.0.0.1")));
  c.port = std::stoi(env("MQTT_PORT", std::to_string(s.value("/broker/port"_json_pointer, 1883))));
  return c;
}

AlarmNode::AlarmNode(AlarmNodeConfig config) : cfg_(std::move(config)), scenario_(createScenario(cfg_.scenario)) {}

AlarmNode::~AlarmNode() { stop(); }

double AlarmNode::seconds() const { return std::chrono::duration<double>(Clock::now() - boot_).count(); }

void AlarmNode::start() {
  mosquitto_lib_init();
  mosq_ = mosquitto_new(("cpp-" + cfg_.nodeId).c_str(), true, this);
  if (!mosq_) throw std::runtime_error("mosquitto_new failed");
  mosquitto_username_pw_set(mosq_, cfg_.nodeId.c_str(), cfg_.password.c_str());
  const std::string offline = "offline";
  mosquitto_will_set(mosq_, statusTopic(cfg_.nodeId).c_str(), static_cast<int>(offline.size()), offline.data(), 0, true);
  mosquitto_connect_callback_set(mosq_, &AlarmNode::onConnect);
  mosquitto_message_callback_set(mosq_, &AlarmNode::onMessage);
  mosquitto_reconnect_delay_set(mosq_, 1, 30, true);
  int rc = mosquitto_connect_async(mosq_, cfg_.host.c_str(), cfg_.port, 5);
  if (rc != MOSQ_ERR_SUCCESS) std::cerr << "[" << cfg_.nodeId << "] connect: " << mosquitto_strerror(rc) << " (retrying)\n";
  mosquitto_loop_start(mosq_);
  std::cout << "[" << cfg_.nodeId << "] C++ module, scenario " << scenario_->name() << ", broker " << cfg_.host << ":" << cfg_.port
            << std::endl;
}

void AlarmNode::stop() {
  if (!mosq_) return;
  mosquitto_disconnect(mosq_);
  mosquitto_loop_stop(mosq_, true);
  mosquitto_destroy(mosq_);
  mosq_ = nullptr;
  mosquitto_lib_cleanup();
}

void AlarmNode::onConnect(mosquitto* m, void* self, int rc) {
  auto* node = static_cast<AlarmNode*>(self);
  if (rc != 0) {
    std::cerr << "[" << node->cfg_.nodeId << "] broker refused the connection (" << mosquitto_connack_string(rc) << ")\n";
    return;
  }
  mosquitto_subscribe(m, nullptr, downTopic(node->cfg_.nodeId).c_str(), 0);
  const std::string online = "online";
  mosquitto_publish(m, nullptr, statusTopic(node->cfg_.nodeId).c_str(), static_cast<int>(online.size()), online.data(), 0, true);
  std::lock_guard<std::mutex> lock(node->mutex_);
  node->connected_ = true;  // every (re)connection starts a new session (spec section 8)
}

void AlarmNode::onMessage(mosquitto*, void* self, const mosquitto_message* msg) {
  auto* node = static_cast<AlarmNode*>(self);
  std::lock_guard<std::mutex> lock(node->mutex_);
  node->inbox_.emplace_back(static_cast<const char*>(msg->payload), static_cast<std::size_t>(msg->payloadlen));
}

void AlarmNode::publish(const std::string& topic, const std::string& payload, bool retain) {
  mosquitto_publish(mosq_, nullptr, topic.c_str(), static_cast<int>(payload.size()), payload.data(), 0, retain);
}

void AlarmNode::newSession() {
  channel_.reset();
  nn_ = alarmproto::randomBytes(16);
  state_ = State::Handshaking;
  nextHello_ = seconds();
}

void AlarmNode::sendHello() {
  publish(upTopic(cfg_.nodeId), alarmproto::sign(cfg_.key, cfg_.nodeId, "HELLO", {{"fw", "0.1.0-cpp"}, {"nn", alarmproto::b64e(nn_)}}));
}

void AlarmNode::heartbeat() {
  std::uniform_int_distribution<int> rssi(-66, -55);
  alarmproto::Fields f = {{"gas", fmt(mq2_.gas() * cfg_.gasPpmPerUnit)},
                     {"temp", fmt(dht_.temperature())},
                     {"hum", fmt(dht_.humidity())},
                     {"lid", "0"},
                     {"up", std::to_string(static_cast<long>(seconds()))},
                     {"rssi", std::to_string(rssi(rng_))}};
  publish(upTopic(cfg_.nodeId), channel_->seal("HB", f));
  nextHb_ = seconds() + kHbInterval;
}

void AlarmNode::handle(const std::string& payload) {
  using Kind = alarmproto::ProtocolError::Kind;
  try {
    const std::string type = alarmproto::peekType(payload);
    if (type == "WELCOME") {
      alarmproto::Message m = alarmproto::verifySigned(cfg_.key, cfg_.nodeId, payload);
      const std::string* nn = m.get("nn");
      const std::string* pn = m.get("pn");
      if (state_ != State::Handshaking || !nn || *nn != alarmproto::b64e(nn_) || !pn) return;  // stale or replayed
      channel_.emplace(alarmproto::deriveSession(cfg_.key, cfg_.nodeId, nn_, alarmproto::b64d(*pn)), cfg_.nodeId, alarmproto::Channel::Role::Node);
      state_ = State::Session;
      lastDown_ = seconds();
      std::cout << "[" << cfg_.nodeId << "] session " << channel_->keys().sid << " established" << std::endl;
      heartbeat();
    } else if (type == "CMD") {
      if (!channel_) return;
      alarmproto::Message m = channel_->open(payload);
      lastDown_ = seconds();
      if (const std::string* b = m.get("buzzer"); b && *b != buzzer_) {
        buzzer_ = *b;
        std::cout << "[" << cfg_.nodeId << "] buzzer " << (buzzer_ == "1" ? "ON" : "off") << std::endl;
      }
      if (const std::string* l = m.get("led"); l && *l != led_) {
        led_ = *l;
        std::cout << "[" << cfg_.nodeId << "] led " << led_ << std::endl;
      }
      const std::string* id = m.get("id");
      publish(upTopic(cfg_.nodeId), channel_->seal("ACK", {{"id", id ? *id : "0"}, {"ok", "1"}}));
    }
  } catch (const alarmproto::ProtocolError& e) {
    if (e.kind == Kind::UnknownSession) return;  // left over from our previous session
    const char* what = e.kind == Kind::AuthFail ? "auth_fail" : e.kind == Kind::Replay ? "replay" : "malformed";
    std::cerr << "[" << cfg_.nodeId << "] REJECTED downlink (" << what << "): " << e.what() << std::endl;
  }
}

void AlarmNode::tick() {
  const double now = seconds();
  // Sensors follow the scenario (same simulators and scenarios as sentinel-edge).
  const SensorTargets t = scenario_->sample(now);
  dht_.update(t.temperature, t.humidity, now - lastTick_);
  mq2_.update(t.gas, now - lastTick_);
  lastTick_ = now;

  std::deque<std::string> inbox;
  bool reconnected = false;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    inbox.swap(inbox_);
    std::swap(reconnected, connected_);
  }
  if (reconnected) newSession();
  for (const auto& payload : inbox) handle(payload);

  if (state_ == State::Handshaking && now >= nextHello_ && !nn_.empty()) {
    sendHello();
    nextHello_ = now + kHelloRetry;
  }
  if (state_ == State::Session) {
    if (now - lastDown_ > kDownlinkTimeout) {
      std::cout << "[" << cfg_.nodeId << "] no downlink for 10 s, new session" << std::endl;
      newSession();
    } else if (now >= nextHb_) {
      heartbeat();
    }
  }
}

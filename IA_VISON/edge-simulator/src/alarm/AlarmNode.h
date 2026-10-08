#pragma once
// An environment module that speaks the alarm's encrypted protocol (protocol/spec.md):
// the same session rules as simulator/alarm_sim/node.py, with readings from the
// DHT22 / MQ-2 simulators driven by a Scenario.

#include "../scenarios/Scenario.h"
#include "../sensors/DHT22Simulator.h"
#include "../sensors/MQ2Simulator.h"

#include <alarm/protocol.hpp>

#include <chrono>
#include <deque>
#include <memory>
#include <mutex>
#include <optional>
#include <random>
#include <string>

struct mosquitto;
struct mosquitto_message;

struct AlarmNodeConfig {
  std::string nodeId = "env-1";
  std::string host = "127.0.0.1";
  int port = 1883;
  std::string password;      // broker password (username = nodeId)
  alarmproto::Bytes key;          // the module's master key
  std::string scenario = "normal";
  double gasPpmPerUnit = 800;  // MQ-2 simulator's 0-1 reading -> ppm (0.50 -> 400 ppm, env-1's limit)
};

// Reads .secrets/dev.json (nodes.<id>.key / .password, broker) and the environment.
AlarmNodeConfig loadConfig();

class AlarmNode {
 public:
  explicit AlarmNode(AlarmNodeConfig config);
  ~AlarmNode();
  void start();
  void tick();  // call every ~50 ms
  void stop();

 private:
  enum class State { Handshaking, Session };
  using Clock = std::chrono::steady_clock;

  void handle(const std::string& payload);
  void newSession();
  void sendHello();
  void heartbeat();
  void publish(const std::string& topic, const std::string& payload, bool retain = false);
  double seconds() const;
  static void onConnect(mosquitto*, void* self, int rc);
  static void onMessage(mosquitto*, void* self, const mosquitto_message* msg);

  AlarmNodeConfig cfg_;
  mosquitto* mosq_ = nullptr;
  std::unique_ptr<Scenario> scenario_;
  DHT22Simulator dht_;
  MQ2Simulator mq2_;
  std::mt19937 rng_{std::random_device{}()};

  State state_ = State::Handshaking;
  std::optional<alarmproto::Channel> channel_;
  alarmproto::Bytes nn_;
  Clock::time_point boot_ = Clock::now();
  double lastTick_ = 0, nextHello_ = 0, nextHb_ = 0, lastDown_ = 0;
  std::string buzzer_ = "0", led_ = "off";

  std::mutex mutex_;
  std::deque<std::string> inbox_;  // filled by the MQTT thread
  bool connected_ = false;
};

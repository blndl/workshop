#pragma once

#include <mosquitto.h>

#include <atomic>
#include <functional>
#include <mutex>
#include <string>
#include <vector>

struct MQTTConfig {
  std::string host;
  int port;
  std::string clientId;
  std::string username;
  std::string password;
  bool tls;
  std::string caCertificate;
  std::string sensorsTopic;
  std::string statusTopic;
  std::string alertsTopic;
  std::string commandsTopic;
  std::string deviceId;
  std::vector<std::string> subscriptions;
  bool listenForCommands = true;
  bool publishPresence = true;
};

class MQTTClient {
public:
  using CommandHandler = std::function<void(const std::string&)>;

  explicit MQTTClient(MQTTConfig config);
  ~MQTTClient();
  MQTTClient(const MQTTClient&) = delete;
  MQTTClient& operator=(const MQTTClient&) = delete;

  void setCommandHandler(CommandHandler handler);
  bool publish(const std::string& topic, const std::string& payload, int qos = 1, bool retain = false);
  bool connected() const;
  const MQTTConfig& config() const;

private:
  static void onConnect(struct mosquitto*, void*, int);
  static void onDisconnect(struct mosquitto*, void*, int);
  static void onMessage(struct mosquitto*, void*, const struct mosquitto_message*);
  void publishStatus(const std::string& status);

  MQTTConfig config_;
  struct mosquitto* client_ = nullptr;
  std::mutex commandMutex_;
  CommandHandler commandHandler_;
  std::atomic_bool connected_{false};
};
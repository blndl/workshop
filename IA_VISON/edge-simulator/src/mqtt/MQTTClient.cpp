#include "MQTTClient.h"

#include <nlohmann/json.hpp>

#include <chrono>
#include <cstdlib>
#include <ctime>
#include <iostream>
#include <stdexcept>
#include <utility>

namespace {
std::string timestampUtc() {
  const std::time_t now = std::time(nullptr);
  std::tm utc{};
#ifdef _WIN32
  gmtime_s(&utc, &now);
#else
  gmtime_r(&now, &utc);
#endif
  char buffer[25];
  std::strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%SZ", &utc);
  return buffer;
}
}

MQTTClient::MQTTClient(MQTTConfig config) : config_(std::move(config)) {
  if (mosquitto_lib_init() != MOSQ_ERR_SUCCESS) throw std::runtime_error("mosquitto_lib_init failed");
  client_ = mosquitto_new(config_.clientId.c_str(), true, this);
  if (!client_) throw std::runtime_error("Could not create MQTT client");

  mosquitto_connect_callback_set(client_, onConnect);
  mosquitto_disconnect_callback_set(client_, onDisconnect);
  mosquitto_message_callback_set(client_, onMessage);
  if (config_.publishPresence) {
    const nlohmann::json offline = {{"device_id", config_.deviceId}, {"status", "offline"},
                                    {"wifi", true}, {"mqtt", false}, {"timestamp", timestampUtc()}};
    const std::string offlinePayload = offline.dump();
    mosquitto_will_set(client_, config_.statusTopic.c_str(), static_cast<int>(offlinePayload.size()),
                       offlinePayload.c_str(), 1, true);
  }
  if (!config_.username.empty()) {
    const int auth = mosquitto_username_pw_set(client_, config_.username.c_str(), config_.password.c_str());
    if (auth != MOSQ_ERR_SUCCESS) throw std::runtime_error(mosquitto_strerror(auth));
  }
  if (config_.tls) {
    const char* ca = config_.caCertificate.empty() ? nullptr : config_.caCertificate.c_str();
    const int tlsResult = mosquitto_tls_set(client_, ca, nullptr, nullptr, nullptr, nullptr);
    if (tlsResult != MOSQ_ERR_SUCCESS) throw std::runtime_error(mosquitto_strerror(tlsResult));
  }
  mosquitto_reconnect_delay_set(client_, 2, 2, false);
  const int connectResult = mosquitto_connect_async(client_, config_.host.c_str(), config_.port, 30);
  if (connectResult != MOSQ_ERR_SUCCESS) {
    std::cerr << "MQTT initial connect: " << mosquitto_strerror(connectResult) << std::endl;
  }
  const int loopResult = mosquitto_loop_start(client_);
  if (loopResult != MOSQ_ERR_SUCCESS) throw std::runtime_error(mosquitto_strerror(loopResult));
}

MQTTClient::~MQTTClient() {
  if (client_) {
    if (connected_ && config_.publishPresence) publishStatus("offline");
    mosquitto_disconnect(client_);
    mosquitto_loop_stop(client_, true);
    mosquitto_destroy(client_);
  }
  mosquitto_lib_cleanup();
}

void MQTTClient::setCommandHandler(CommandHandler handler) {
  std::lock_guard<std::mutex> lock(commandMutex_);
  commandHandler_ = std::move(handler);
}

bool MQTTClient::publish(const std::string& topic, const std::string& payload, int qos, bool retain) {
  if (!connected_) return false;
  return mosquitto_publish(client_, nullptr, topic.c_str(), static_cast<int>(payload.size()),
                           payload.data(), qos, retain) == MOSQ_ERR_SUCCESS;
}

bool MQTTClient::connected() const { return connected_.load(); }
const MQTTConfig& MQTTClient::config() const { return config_; }

void MQTTClient::onConnect(struct mosquitto* client, void* context, int result) {
  auto* self = static_cast<MQTTClient*>(context);
  if (result != 0) {
    self->connected_ = false;
    std::cerr << "MQTT connection failed: " << mosquitto_connack_string(result) << std::endl;
    return;
  }
  self->connected_ = true;
  std::cout << "MQTT connected to " << self->config_.host << ':' << self->config_.port << std::endl;
  for (const auto& topic : self->config_.subscriptions) {
    mosquitto_subscribe(client, nullptr, topic.c_str(), 1);
  }
  if (self->config_.listenForCommands) {
    mosquitto_subscribe(client, nullptr, self->config_.commandsTopic.c_str(), 1);
  }
  if (self->config_.publishPresence) self->publishStatus("online");
}

void MQTTClient::onDisconnect(struct mosquitto*, void* context, int result) {
  auto* self = static_cast<MQTTClient*>(context);
  const bool wasConnected = self->connected_;
  self->connected_ = false;
  if (wasConnected || result != 0) {
    std::cerr << "MQTT disconnected; retrying in 2s..." << std::endl;
  }
}

void MQTTClient::onMessage(struct mosquitto*, void* context, const struct mosquitto_message* message) {
  auto* self = static_cast<MQTTClient*>(context);
  if (!message || !message->payload || message->payloadlen <= 0) return;
  CommandHandler handler;
  {
    std::lock_guard<std::mutex> lock(self->commandMutex_);
    handler = self->commandHandler_;
  }
  if (handler) handler(std::string(static_cast<const char*>(message->payload), message->payloadlen));
}

void MQTTClient::publishStatus(const std::string& status) {
  const nlohmann::json payload = {{"device_id", config_.deviceId}, {"status", status},
                                  {"wifi", true}, {"mqtt", status == "online"},
                                  {"timestamp", timestampUtc()}};
  const std::string serialized = payload.dump();
  mosquitto_publish(client_, nullptr, config_.statusTopic.c_str(), static_cast<int>(serialized.size()),
                    serialized.c_str(), 1, true);
}
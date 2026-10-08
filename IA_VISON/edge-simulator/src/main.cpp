#include "actuators/Buzzer.h"
#include "actuators/LED.h"
#include "alerts/AlertEvaluator.h"
#include "display/OLEDDisplay.h"
#include "mqtt/MQTTClient.h"
#include "scenarios/Scenario.h"
#include "sensors/DHT22Simulator.h"
#include "sensors/MQ2Simulator.h"
#include "sensors/PIRSimulator.h"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <ctime>
#include <iostream>
#include <mutex>
#include <set>
#include <thread>
#include <utility>

namespace {
std::string env(const char* name, const std::string& fallback) {
  const char* value = std::getenv(name);
  return value && *value ? value : fallback;
}

int envInt(const char* name, int fallback) {
  try { return std::max(1, std::stoi(env(name, std::to_string(fallback)))); }
  catch (...) { return fallback; }
}

bool envBool(const char* name, bool fallback) {
  const std::string value = env(name, fallback ? "true" : "false");
  return value == "true" || value == "1" || value == "yes";
}

double envDouble(const char* name, double fallback) {
  try { return std::stod(env(name, std::to_string(fallback))); }
  catch (...) { return fallback; }
}

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

MQTTConfig mqttConfig(const std::string& clientId, const std::string& deviceId,
                      const std::string& prefix) {
  return {env("MQTT_HOST", "localhost"), envInt("MQTT_PORT", 1883), clientId,
          env("MQTT_USERNAME", ""), env("MQTT_PASSWORD", ""), envBool("MQTT_TLS", false),
          env("MQTT_CA_CERT", ""), env("MQTT_SENSORS_TOPIC", prefix + "/sensors"),
          env("MQTT_STATUS_TOPIC", prefix + "/status"), env("MQTT_ALERTS_TOPIC", prefix + "/alerts"),
          env("MQTT_COMMANDS_TOPIC", prefix + "/commands"), deviceId};
}

int runSensor(const std::string& kind, const std::string& deviceId, const std::string& prefix) {
  auto scenario = createScenario(env("SCENARIO", "normal"));
  const int intervalMs = envInt("SENSOR_INTERVAL_MS", 1000);
  const std::string internalTopic = "sentinel/internal/" + deviceId + "/" + kind;
  const std::string clientId = deviceId + "-" + kind;
  auto config = mqttConfig(clientId, deviceId, prefix);
  config.listenForCommands = false;
  config.publishPresence = false;
  MQTTClient mqtt(std::move(config));

  DHT22Simulator dht;
  MQ2Simulator mq2;
  PIRSimulator pir;
  const auto startedAt = std::chrono::steady_clock::now();
  auto previousTick = startedAt;
  auto nextPublish = startedAt;
  std::cout << "Sensor container " << kind << " publishing to " << internalTopic
            << " with scenario=" << scenario->name() << std::endl;

  while (true) {
    const auto now = std::chrono::steady_clock::now();
    const double elapsed = std::chrono::duration<double>(now - startedAt).count();
    const double delta = std::chrono::duration<double>(now - previousTick).count();
    previousTick = now;
    const SensorTargets target = scenario->sample(elapsed);
    dht.update(target.temperature, target.humidity, delta);
    mq2.update(target.gas, delta);
    pir.update(target.motion);

    if (now >= nextPublish) {
      nlohmann::json payload = {{"device_id", deviceId}, {"sensor", kind}, {"timestamp", timestampUtc()}};
      if (kind == "dht22") {
        payload["temperature"] = std::round(dht.temperature() * 10.0) / 10.0;
        payload["humidity"] = std::round(dht.humidity() * 10.0) / 10.0;
      } else if (kind == "mq2") {
        payload["gas"] = std::round(mq2.gas() * 100.0) / 100.0;
      } else {
        payload["motion"] = pir.motion();
      }
      mqtt.publish(internalTopic, payload.dump());
      nextPublish = now + std::chrono::milliseconds(intervalMs);
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(30));
  }
}

int runCoordinator(const std::string& deviceId, const std::string& prefix) {
  const int intervalMs = envInt("SENSOR_INTERVAL_MS", 1000);
  const AlertThresholds thresholds{envDouble("ALERT_GAS_THRESHOLD", 0.50),
                                   envDouble("ALERT_TEMPERATURE_THRESHOLD", 35.0),
                                   envDouble("ALERT_HUMIDITY_MIN", 40.0),
                                   envDouble("ALERT_HUMIDITY_MAX", 60.0)};
  if (thresholds.humidityMinimum >= thresholds.humidityMaximum) {
    throw std::invalid_argument("ALERT_HUMIDITY_MIN must be lower than ALERT_HUMIDITY_MAX");
  }
  const std::string internalPrefix = "sentinel/internal/" + deviceId + "/";
  auto config = mqttConfig(env("MQTT_CLIENT_ID", deviceId), deviceId, prefix);
  config.subscriptions = {internalPrefix + "dht22", internalPrefix + "mq2", internalPrefix + "pir",
                          config.alertsTopic};
  MQTTClient mqtt(std::move(config));
  Buzzer buzzer;
  LED statusLed;
  OLEDDisplay display;

  SensorTargets current{24.0, 50.0, 0.08, false};
  std::mutex sensorMutex;
  std::mutex payloadMutex;
  std::mutex alertStateMutex;
  bool dirty = false;
  std::string latestTimestamp = timestampUtc();
  std::set<std::string> previousAlerts;
  mqtt.setCommandHandler([&](const std::string& raw) {
    try {
      const auto payload = nlohmann::json::parse(raw);
      if (payload.contains("event") && payload.contains("alerts") && payload["alerts"].is_array()) {
        std::set<std::string> retainedAlerts;
        for (const auto& alert : payload["alerts"]) {
          if (alert.is_string()) retainedAlerts.insert(alert.get<std::string>());
        }
        std::lock_guard<std::mutex> alertLock(alertStateMutex);
        previousAlerts = std::move(retainedAlerts);
        return;
      }
      const std::string kind = payload.value("sensor", std::string{});
      if (kind == "dht22" || kind == "mq2" || kind == "pir") {
        std::lock_guard<std::mutex> payloadLock(payloadMutex);
        {
          std::lock_guard<std::mutex> sensorLock(sensorMutex);
          if (kind == "dht22") {
            current.temperature = payload.at("temperature").get<double>();
            current.humidity = payload.at("humidity").get<double>();
          } else if (kind == "mq2") {
            current.gas = payload.at("gas").get<double>();
          } else {
            current.motion = payload.at("motion").get<bool>();
          }
        }
        latestTimestamp = payload.value("timestamp", timestampUtc());
        dirty = true;
      } else {
        const std::string command = payload.at("command").get<std::string>();
        const unsigned duration = payload.value("duration", 0U);
        std::cout << "[Command] " << command << std::endl;
        if (command == "BUZZER_ON") buzzer.set(true, duration);
        else if (command == "BUZZER_OFF" || command == "RESET_ALERT") buzzer.set(false);
        else if (command == "LED_RED") statusLed.set("RED");
        else if (command == "LED_GREEN") statusLed.set("GREEN");
        else if (command == "LED_OFF") statusLed.set("OFF");
        else std::cerr << "Unknown command: " << command << std::endl;
      }
    } catch (const std::exception& error) {
      std::cerr << "Invalid MQTT message: " << error.what() << std::endl;
    }
  });

  std::cout << "Sentinel-X edge coordinator; device=" << deviceId
            << ", interval=" << intervalMs << "ms" << std::endl;
  auto nextPublish = std::chrono::steady_clock::now();
  auto nextDisplay = nextPublish;
  while (true) {
    const auto now = std::chrono::steady_clock::now();
    buzzer.tick();
    SensorTargets snapshot;
    std::string sensorTimestamp;
    bool shouldPublish = false;
    {
      std::lock_guard<std::mutex> payloadLock(payloadMutex);
      shouldPublish = now >= nextPublish && dirty;
      if (shouldPublish) {
        std::lock_guard<std::mutex> sensorLock(sensorMutex);
        snapshot = current;
        sensorTimestamp = latestTimestamp;
        dirty = false;
        nextPublish = now + std::chrono::milliseconds(intervalMs);
      }
    }

    if (shouldPublish) {
      nlohmann::json payload = {{"device_id", deviceId}, {"timestamp", sensorTimestamp},
                                {"temperature", snapshot.temperature}, {"humidity", snapshot.humidity},
                                {"gas", snapshot.gas}, {"motion", snapshot.motion}};
      mqtt.publish(mqtt.config().sensorsTopic, payload.dump());

      const auto alerts = evaluateAlerts(snapshot, thresholds);
      std::set<std::string> alertCodes;
      for (const auto& alert : alerts) alertCodes.insert(alert.code);
      std::set<std::string> previousAlertSnapshot;
      {
        std::lock_guard<std::mutex> alertLock(alertStateMutex);
        previousAlertSnapshot = previousAlerts;
      }
      if (alertCodes != previousAlertSnapshot) {
        if (!alertCodes.empty()) {
          buzzer.set(true);
          statusLed.set("RED");
        } else if (!previousAlerts.empty()) {
          buzzer.set(false);
          statusLed.set("GREEN");
        }
        nlohmann::json details = nlohmann::json::array();
        for (const auto& alert : alerts) {
          details.push_back({{"code", alert.code}, {"sensor", alert.sensor},
                             {"severity", alert.severity}, {"message", alert.message}, {"value", alert.value},
                             {"condition", alert.condition}, {"threshold", alert.threshold}});
        }
        nlohmann::json alertPayload = {{"device_id", deviceId},
                                       {"event", alertCodes.empty() ? "resolved" : (previousAlertSnapshot.empty() ? "triggered" : "updated")},
                                       {"active", !alertCodes.empty()}, {"alerts", alertCodes},
                                       {"details", details}, {"timestamp", sensorTimestamp}};
        mqtt.publish(mqtt.config().alertsTopic, alertPayload.dump(), 1, true);
        if (!alertCodes.empty()) {
          std::cerr << "[ALERTE] ";
          for (size_t index = 0; index < alerts.size(); ++index) {
            if (index) std::cerr << " | ";
            std::cerr << alerts[index].message;
          }
          std::cerr << std::endl;
        } else {
          std::cout << "[RESOLUTION] Toutes les mesures sont revenues dans les limites." << std::endl;
        }
        std::lock_guard<std::mutex> alertLock(alertStateMutex);
        previousAlerts = std::move(alertCodes);
      }
    }

    if (now >= nextDisplay) {
      SensorTargets snapshot;
      {
        std::lock_guard<std::mutex> sensorLock(sensorMutex);
        snapshot = current;
      }
      const auto activeAlerts = evaluateAlerts(snapshot, thresholds);
      display.render(deviceId, env("SCENARIO", "normal"), mqtt.connected(), snapshot, !activeAlerts.empty());
      nextDisplay = now + std::chrono::seconds(5);
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(30));
  }
}
}

int main() {
  try {
    const std::string deviceId = env("MQTT_DEVICE_ID", env("MQTT_CLIENT_ID", "ESP8266-001"));
    const std::string prefix = "sentinel/edge/" + deviceId;
    const std::string role = env("ROLE", "coordinator");
    if (role == "sensor") {
      const std::string kind = env("SENSOR_KIND", "dht22");
      if (kind != "dht22" && kind != "mq2" && kind != "pir") {
        throw std::invalid_argument("SENSOR_KIND must be dht22, mq2, or pir");
      }
      return runSensor(kind, deviceId, prefix);
    }
    return runCoordinator(deviceId, prefix);
  } catch (const std::exception& error) {
    std::cerr << "Fatal: " << error.what() << std::endl;
    return 1;
  }
}

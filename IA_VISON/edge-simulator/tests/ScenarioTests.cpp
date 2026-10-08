#include "alerts/AlertEvaluator.h"
#include "scenarios/Scenario.h"
#include "sensors/DHT22Simulator.h"
#include "sensors/MQ2Simulator.h"

#include <nlohmann/json.hpp>

#include <cmath>
#include <iostream>
#include <stdexcept>

namespace {
void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}
}

int main() {
  const auto normal = createScenario("normal");
  const auto baseline = normal->sample(0.0);
  const auto later = normal->sample(1.0);
  require(baseline.temperature >= 22.0 && baseline.temperature <= 27.0, "normal temperature range");
  require(baseline.humidity >= 40.0 && baseline.humidity <= 60.0, "normal humidity range");
  require(std::abs(later.temperature - baseline.temperature) < 0.1, "normal temperature continuity");

  const auto gas = createScenario("gas_leak");
  require(gas->sample(8.0).gas > gas->sample(1.0).gas, "gas leak ramp");
  const auto heat = createScenario("overheat");
  require(heat->sample(8.0).temperature > heat->sample(1.0).temperature, "overheat ramp");
  const auto intrusion = createScenario("intrusion");
  require(intrusion->sample(1.0).motion && !intrusion->sample(15.0).motion, "intrusion duration");
  const auto combined = createScenario("combined_attack");
  const auto attack = combined->sample(10.0);
  require(attack.temperature > 24.0 && attack.gas > 0.10 && attack.motion, "combined attack signals");
    const auto dry = createScenario("humidity_low");
    const auto humid = createScenario("humidity_high");
    require(dry->sample(0.0).humidity < 40.0, "low humidity scenario");
    require(humid->sample(0.0).humidity > 60.0, "high humidity scenario");

    const AlertThresholds thresholds{};
    const auto normalAlerts = evaluateAlerts({24.0, 50.0, 0.10, false}, thresholds);
    require(normalAlerts.empty(), "normal readings do not emit alert conditions");
    const auto lowHumidityAlerts = evaluateAlerts({24.0, 35.0, 0.10, false}, thresholds);
    require(lowHumidityAlerts.size() == 1 && lowHumidityAlerts[0].code == "humidity_low", "low humidity alert");
    require(lowHumidityAlerts[0].message.find("35.0 %") != std::string::npos &&
      lowHumidityAlerts[0].message.find("40.0 %") != std::string::npos, "low humidity message has value and limit");
    const auto highHumidityAlerts = evaluateAlerts({24.0, 68.5, 0.10, false}, thresholds);
    require(highHumidityAlerts.size() == 1 && highHumidityAlerts[0].code == "humidity_high", "high humidity alert");
    const auto motionAlerts = evaluateAlerts({24.0, 50.0, 0.10, true}, thresholds);
    require(motionAlerts.size() == 1 && motionAlerts[0].code == "intrusion", "motion alert");
    const auto combinedAlerts = evaluateAlerts({37.0, 65.0, 0.70, true}, thresholds);
    require(combinedAlerts.size() == 4, "combined sensor alert conditions");

  DHT22Simulator dht;
  dht.update(40.0, 70.0, 1.0);
  require(std::abs(dht.temperature() - 24.8) < 0.001, "DHT22 temperature slew");
  require(std::abs(dht.humidity() - 52.0) < 0.001, "DHT22 humidity slew");
  MQ2Simulator mq2;
  mq2.update(0.8, 1.0);
  require(std::abs(mq2.gas() - 0.16) < 0.001, "MQ-2 gas slew");

  const nlohmann::json sensorPayload = {{"device_id", "ESP8266-001"},
                                        {"timestamp", "2026-10-07T10:30:00Z"},
                                        {"temperature", 24.7}, {"humidity", 51.2},
                                        {"gas", 0.18}, {"motion", false}};
  require(sensorPayload.size() == 6, "sensor JSON field count");
  require(sensorPayload.at("temperature").is_number(), "temperature JSON type");
  require(sensorPayload.at("motion").is_boolean(), "motion JSON type");
  const auto roundTrip = nlohmann::json::parse(sensorPayload.dump());
  require(roundTrip.at("device_id") == "ESP8266-001", "JSON serialization round trip");

  std::cout << "Scenario, sensor ramp and JSON contract tests passed" << std::endl;
}
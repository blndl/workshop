#pragma once

#include "../scenarios/Scenario.h"

#include <string>
#include <vector>

struct AlertThresholds {
  double gas = 0.50;
  double temperature = 35.0;
  double humidityMinimum = 40.0;
  double humidityMaximum = 60.0;
};

struct AlertDetail {
  std::string code;
  std::string sensor;
  std::string severity;
  std::string message;
  double value;
  std::string condition;
  double threshold;
};

std::vector<AlertDetail> evaluateAlerts(const SensorTargets& sensors, const AlertThresholds& thresholds);
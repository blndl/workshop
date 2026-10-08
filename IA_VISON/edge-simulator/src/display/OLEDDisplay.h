#pragma once

#include "../scenarios/Scenario.h"

#include <string>

class OLEDDisplay {
public:
  void render(const std::string& deviceId, const std::string& scenario,
              bool mqttConnected, const SensorTargets& sensors, bool alarm) const;
};
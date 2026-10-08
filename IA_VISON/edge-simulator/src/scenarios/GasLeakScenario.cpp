#include "Scenario.h"

#include <algorithm>

std::string GasLeakScenario::name() const { return "gas_leak"; }

SensorTargets GasLeakScenario::sample(double elapsedSeconds) const {
  return {24.0, 50.0, std::min(0.95, 0.10 + 0.06 * std::max(0.0, elapsedSeconds)), false};
}
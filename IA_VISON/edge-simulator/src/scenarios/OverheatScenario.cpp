#include "Scenario.h"

#include <algorithm>

std::string OverheatScenario::name() const { return "overheat"; }

SensorTargets OverheatScenario::sample(double elapsedSeconds) const {
  return {std::min(60.0, 24.0 + 1.5 * std::max(0.0, elapsedSeconds)), 48.0, 0.08, false};
}
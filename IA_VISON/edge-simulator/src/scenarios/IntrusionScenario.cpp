#include "Scenario.h"

#include <cmath>

std::string IntrusionScenario::name() const { return "intrusion"; }

SensorTargets IntrusionScenario::sample(double elapsedSeconds) const {
  const double phase = std::fmod(std::max(0.0, elapsedSeconds), 30.0);
  return {24.0, 50.0, 0.08, phase < 12.0};
}
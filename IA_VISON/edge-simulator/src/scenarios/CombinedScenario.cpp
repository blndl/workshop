#include "Scenario.h"

#include <algorithm>
#include <cmath>

std::string CombinedScenario::name() const { return "combined_attack"; }

SensorTargets CombinedScenario::sample(double elapsedSeconds) const {
  const double elapsed = std::max(0.0, elapsedSeconds);
  return {std::min(60.0, 24.0 + 1.2 * elapsed), 50.0,
          std::min(0.95, 0.10 + 0.045 * elapsed), std::fmod(elapsed, 40.0) < 25.0};
}
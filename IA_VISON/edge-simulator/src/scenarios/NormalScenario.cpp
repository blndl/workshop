#include "Scenario.h"

#include <cmath>

std::string NormalScenario::name() const { return "normal"; }

SensorTargets NormalScenario::sample(double elapsedSeconds) const {
  return {24.0 + 0.8 * std::sin(elapsedSeconds / 45.0),
          50.0 + 3.0 * std::sin(elapsedSeconds / 60.0),
          0.08 + 0.015 * (1.0 + std::sin(elapsedSeconds / 18.0)),
          std::fmod(elapsedSeconds, 47.0) < 2.0};
}
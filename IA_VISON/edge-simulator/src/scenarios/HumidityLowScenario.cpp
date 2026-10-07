#include "Scenario.h"

std::string HumidityLowScenario::name() const { return "humidity_low"; }
SensorTargets HumidityLowScenario::sample(double) const { return {24.0, 25.0, 0.08, false}; }
#include "Scenario.h"

std::string HumidityHighScenario::name() const { return "humidity_high"; }
SensorTargets HumidityHighScenario::sample(double) const { return {24.0, 75.0, 0.08, false}; }
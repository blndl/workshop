#include "Scenario.h"

#include <stdexcept>

std::unique_ptr<Scenario> createScenario(const std::string& name) {
  if (name == "normal") return std::make_unique<NormalScenario>();
  if (name == "gas_leak") return std::make_unique<GasLeakScenario>();
  if (name == "overheat") return std::make_unique<OverheatScenario>();
  if (name == "intrusion") return std::make_unique<IntrusionScenario>();
  if (name == "humidity_low") return std::make_unique<HumidityLowScenario>();
  if (name == "humidity_high") return std::make_unique<HumidityHighScenario>();
  if (name == "combined_attack") return std::make_unique<CombinedScenario>();
  throw std::invalid_argument("Unknown scenario: " + name);
}
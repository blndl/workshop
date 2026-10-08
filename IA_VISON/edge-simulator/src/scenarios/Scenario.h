#pragma once

#include <memory>
#include <string>

struct SensorTargets {
  double temperature;
  double humidity;
  double gas;
  bool motion;
};

class Scenario {
public:
  virtual ~Scenario() = default;
  virtual std::string name() const = 0;
  virtual SensorTargets sample(double elapsedSeconds) const = 0;
};

class NormalScenario final : public Scenario {
public:
  std::string name() const override;
  SensorTargets sample(double elapsedSeconds) const override;
};

class GasLeakScenario final : public Scenario {
public:
  std::string name() const override;
  SensorTargets sample(double elapsedSeconds) const override;
};

class OverheatScenario final : public Scenario {
public:
  std::string name() const override;
  SensorTargets sample(double elapsedSeconds) const override;
};

class IntrusionScenario final : public Scenario {
public:
  std::string name() const override;
  SensorTargets sample(double elapsedSeconds) const override;
};

class HumidityLowScenario final : public Scenario {
public:
  std::string name() const override;
  SensorTargets sample(double elapsedSeconds) const override;
};

class HumidityHighScenario final : public Scenario {
public:
  std::string name() const override;
  SensorTargets sample(double elapsedSeconds) const override;
};

class CombinedScenario final : public Scenario {
public:
  std::string name() const override;
  SensorTargets sample(double elapsedSeconds) const override;
};

std::unique_ptr<Scenario> createScenario(const std::string& name);
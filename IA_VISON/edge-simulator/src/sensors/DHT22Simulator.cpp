#include "DHT22Simulator.h"

#include <algorithm>

DHT22Simulator::DHT22Simulator(double temperature, double humidity)
    : temperature_(temperature), humidity_(humidity) {}

void DHT22Simulator::update(double targetTemperature, double targetHumidity, double elapsedSeconds) {
  const double step = std::max(0.0, elapsedSeconds);
  const double temperatureDelta = targetTemperature - temperature_;
  const double humidityDelta = targetHumidity - humidity_;
  temperature_ += std::clamp(temperatureDelta, -0.8 * step, 0.8 * step);
  humidity_ += std::clamp(humidityDelta, -2.0 * step, 2.0 * step);
}

double DHT22Simulator::temperature() const { return temperature_; }
double DHT22Simulator::humidity() const { return humidity_; }
#pragma once

class DHT22Simulator {
public:
  DHT22Simulator(double temperature = 24.0, double humidity = 50.0);
  void update(double targetTemperature, double targetHumidity, double elapsedSeconds);
  double temperature() const;
  double humidity() const;

private:
  double temperature_;
  double humidity_;
};
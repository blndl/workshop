#pragma once

class MQ2Simulator {
public:
  explicit MQ2Simulator(double gas = 0.08);
  void update(double targetGas, double elapsedSeconds);
  double gas() const;

private:
  double gas_;
};
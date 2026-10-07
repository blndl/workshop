#include "MQ2Simulator.h"

#include <algorithm>

MQ2Simulator::MQ2Simulator(double gas) : gas_(gas) {}

void MQ2Simulator::update(double targetGas, double elapsedSeconds) {
  const double maximumStep = 0.08 * std::max(0.0, elapsedSeconds);
  gas_ += std::clamp(targetGas - gas_, -maximumStep, maximumStep);
}

double MQ2Simulator::gas() const { return gas_; }
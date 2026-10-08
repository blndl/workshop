#include "PIRSimulator.h"

void PIRSimulator::update(bool motion) { motion_ = motion; }
bool PIRSimulator::motion() const { return motion_; }
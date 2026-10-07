#include "Buzzer.h"

#include <iostream>

void Buzzer::set(bool enabled, unsigned durationMs) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (on_ == enabled && (!enabled || durationMs == 0)) return;
  on_ = enabled;
  expiresAt_ = enabled && durationMs > 0
                   ? std::chrono::steady_clock::now() + std::chrono::milliseconds(durationMs)
                   : std::chrono::steady_clock::time_point{};
  std::cout << "[Buzzer] " << (on_ ? "ON" : "OFF") << std::endl;
}

void Buzzer::tick() {
  std::lock_guard<std::mutex> lock(mutex_);
  if (on_ && expiresAt_ != std::chrono::steady_clock::time_point{} &&
      std::chrono::steady_clock::now() >= expiresAt_) {
    on_ = false;
    expiresAt_ = {};
    std::cout << "[Buzzer] OFF" << std::endl;
  }
}

bool Buzzer::isOn() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return on_;
}
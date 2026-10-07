#pragma once

#include <chrono>
#include <mutex>

class Buzzer {
public:
  void set(bool enabled, unsigned durationMs = 0);
  void tick();
  bool isOn() const;

private:
  mutable std::mutex mutex_;
  bool on_ = false;
  std::chrono::steady_clock::time_point expiresAt_{};
};
#pragma once

#include <mutex>
#include <string>

class LED {
public:
  void set(const std::string& color);
  std::string color() const;

private:
  mutable std::mutex mutex_;
  std::string color_ = "OFF";
};
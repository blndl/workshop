#include "LED.h"

#include <iostream>

void LED::set(const std::string& color) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (color_ == color) return;
  color_ = color;
  std::cout << "[LED] " << color_ << std::endl;
}

std::string LED::color() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return color_;
}
#pragma once

class PIRSimulator {
public:
  void update(bool motion);
  bool motion() const;

private:
  bool motion_ = false;
};
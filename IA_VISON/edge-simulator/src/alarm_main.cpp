// alarm-node: this simulator as a module of the alarm system (env-1 by default).
//   NODE_ID=env-1 SCENARIO=gas_leak SECRETS=.secrets/dev.json alarm-node
#include "alarm/AlarmNode.h"

#include <atomic>
#include <csignal>
#include <iostream>
#include <thread>

static std::atomic<bool> running{true};

int main() {
  std::signal(SIGINT, [](int) { running = false; });
  std::signal(SIGTERM, [](int) { running = false; });
  try {
    AlarmNode node(loadConfig());
    node.start();
    while (running) {
      node.tick();
      std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    node.stop();
  } catch (const std::exception& e) {
    std::cerr << "alarm-node: " << e.what() << std::endl;
    return 1;
  }
  return 0;
}

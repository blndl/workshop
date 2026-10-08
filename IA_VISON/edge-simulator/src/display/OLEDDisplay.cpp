#include "OLEDDisplay.h"

#include <iomanip>
#include <iostream>

void OLEDDisplay::render(const std::string& deviceId, const std::string& scenario,
                         bool mqttConnected, const SensorTargets& sensors, bool alarm) const {
  std::cout << "\n================================\n"
            << "          SENTINEL-X\n"
            << "================================\n"
            << "Device     : " << deviceId << '\n'
            << "Scenario   : " << scenario << '\n'
            << "WiFi       : SIMULATED\n"
            << "MQTT       : " << (mqttConnected ? "CONNECTED" : "DISCONNECTED") << '\n'
            << std::fixed << std::setprecision(1)
            << "Temperature: " << sensors.temperature << " C\n"
            << "Humidity   : " << sensors.humidity << " %\n"
            << std::setprecision(2) << "Gas        : " << sensors.gas << '\n'
            << "Motion     : " << (sensors.motion ? "ON" : "OFF") << '\n'
            << "Alarm      : " << (alarm ? "ON" : "OFF") << '\n'
            << "================================" << std::endl;
}
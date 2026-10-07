#include "AlertEvaluator.h"

#include <iomanip>
#include <sstream>

namespace {
std::string number(double value, int precision) {
  std::ostringstream stream;
  stream << std::fixed << std::setprecision(precision) << value;
  return stream.str();
}
}

std::vector<AlertDetail> evaluateAlerts(const SensorTargets& sensors, const AlertThresholds& thresholds) {
  std::vector<AlertDetail> alerts;
  if (sensors.gas >= thresholds.gas) {
    alerts.push_back({"gas", "MQ-2", "critical", "Gaz détecté : " + number(sensors.gas, 2) +
                      " (seuil maximum " + number(thresholds.gas, 2) + ").",
                      sensors.gas, ">=", thresholds.gas});
  }
  if (sensors.temperature >= thresholds.temperature) {
    alerts.push_back({"overheat", "DHT22", "critical", "Température trop élevée : " + number(sensors.temperature, 1) +
                      " °C (maximum " + number(thresholds.temperature, 1) + " °C).",
                      sensors.temperature, ">=", thresholds.temperature});
  }
  if (sensors.humidity < thresholds.humidityMinimum) {
    alerts.push_back({"humidity_low", "DHT22", "warning", "Humidité trop basse : " + number(sensors.humidity, 1) +
                      " % (minimum " + number(thresholds.humidityMinimum, 1) + " %).",
                      sensors.humidity, "<", thresholds.humidityMinimum});
  } else if (sensors.humidity > thresholds.humidityMaximum) {
    alerts.push_back({"humidity_high", "DHT22", "warning", "Humidité trop élevée : " + number(sensors.humidity, 1) +
                      " % (maximum " + number(thresholds.humidityMaximum, 1) + " %).",
                      sensors.humidity, ">", thresholds.humidityMaximum});
  }
  if (sensors.motion) {
    alerts.push_back({"intrusion", "PIR HC-SR501", "warning", "Mouvement détecté par le capteur PIR.", 1.0, "=", 1.0});
  }
  return alerts;
}
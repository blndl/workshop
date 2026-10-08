cmake_minimum_required(VERSION 3.16)
project(sentinel_edge_simulator LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(PkgConfig REQUIRED)
pkg_check_modules(MOSQUITTO REQUIRED IMPORTED_TARGET libmosquitto)
find_package(nlohmann_json 3.2.0 REQUIRED)
find_package(Threads REQUIRED)

add_library(edge_core
  src/alerts/AlertEvaluator.cpp
  src/sensors/DHT22Simulator.cpp
  src/sensors/MQ2Simulator.cpp
  src/sensors/PIRSimulator.cpp
  src/scenarios/Scenario.cpp
  src/scenarios/NormalScenario.cpp
  src/scenarios/GasLeakScenario.cpp
  src/scenarios/OverheatScenario.cpp
  src/scenarios/IntrusionScenario.cpp
  src/scenarios/HumidityLowScenario.cpp
  src/scenarios/HumidityHighScenario.cpp
  src/scenarios/CombinedScenario.cpp
)
target_include_directories(edge_core PUBLIC src)

add_executable(sentinel-edge
  src/main.cpp
  src/mqtt/MQTTClient.cpp
  src/display/OLEDDisplay.cpp
  src/actuators/Buzzer.cpp
  src/actuators/LED.cpp
)
target_link_libraries(sentinel-edge PRIVATE edge_core PkgConfig::MOSQUITTO nlohmann_json::nlohmann_json Threads::Threads)

# alarm-node: this simulator as a module of the alarm system, over the encrypted protocol.
# Needs the C++ protocol library (protocol/cpp in the main repo) and OpenSSL; skipped otherwise.
set(ALARM_PROTOCOL_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../protocol/cpp" CACHE PATH "protocol/cpp")
if(EXISTS "${ALARM_PROTOCOL_DIR}/CMakeLists.txt")
  add_subdirectory("${ALARM_PROTOCOL_DIR}" alarm_protocol)
  add_executable(alarm-node src/alarm_main.cpp src/alarm/AlarmNode.cpp)
  target_link_libraries(alarm-node PRIVATE edge_core alarm_protocol PkgConfig::MOSQUITTO nlohmann_json::nlohmann_json Threads::Threads)
else()
  message(STATUS "alarm-node skipped: no ${ALARM_PROTOCOL_DIR}")
endif()

include(CTest)
if(BUILD_TESTING)
  add_executable(edge-tests tests/ScenarioTests.cpp)
  target_link_libraries(edge-tests PRIVATE edge_core nlohmann_json::nlohmann_json)
  add_test(NAME edge-scenarios-and-json COMMAND edge-tests)
endif()
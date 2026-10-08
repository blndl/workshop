# Alarm protocol v1 in C++17 (OpenSSL). Used by the C++ simulator, and the base for the firmware.
cmake_minimum_required(VERSION 3.16)
project(alarm_protocol LANGUAGES CXX)

if(NOT TARGET alarm_protocol)
  set(CMAKE_CXX_STANDARD 17)
  set(CMAKE_CXX_STANDARD_REQUIRED ON)
  find_package(OpenSSL REQUIRED)

  add_library(alarm_protocol src/protocol.cpp)
  target_include_directories(alarm_protocol PUBLIC include)
  target_link_libraries(alarm_protocol PUBLIC OpenSSL::Crypto)
  target_compile_options(alarm_protocol PRIVATE -Wall -Wextra)

  include(CTest)
  if(BUILD_TESTING)
    find_package(nlohmann_json 3.2.0 REQUIRED)
    add_executable(alarm-protocol-tests tests/test_protocol.cpp)
    target_link_libraries(alarm-protocol-tests PRIVATE alarm_protocol nlohmann_json::nlohmann_json)
    add_test(NAME protocol-vectors COMMAND alarm-protocol-tests ${CMAKE_CURRENT_SOURCE_DIR}/../test-vectors.json)
  endif()
endif()

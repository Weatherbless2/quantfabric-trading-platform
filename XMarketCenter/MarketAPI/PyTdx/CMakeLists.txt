cmake_minimum_required(VERSION 3.16)
project(PyTdxMarket)

set(CMAKE_CXX_FLAGS "-fPIC")
set(CMAKE_INCLUDE_CURRENT_DIR ON)
set(CMAKE_BUILD_TYPE "RelWithDebInfo")
set(CMAKE_CXX_STANDARD 17)

set(AppVersion 0.1.0)
set(MarketGateWay_Version ${PROJECT_NAME}_${AppVersion})
set(APIVersion "PyTdxBridge 1.0.0")

execute_process(
    COMMAND git rev-parse --short HEAD
    OUTPUT_VARIABLE SO_COMMITID
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
)
execute_process(
    COMMAND git rev-parse --short HEAD
    OUTPUT_VARIABLE SO_UTILS_COMMITID
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/../../../Utils
)

add_definitions(-DSO_COMMITID="${SO_COMMITID}")
add_definitions(-DSO_UTILS_COMMITID="${SO_UTILS_COMMITID}")
add_definitions(-DAPI_VERSION="${APIVersion}")

include_directories(${CMAKE_CURRENT_SOURCE_DIR}/../../../Utils)
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/../../MarketAPI)
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/../..)
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/../../../XAPI/SPDLog/1.8.5/include)
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/../../../XAPI/YAML-CPP/0.8.0/include)

link_directories(${CMAKE_CURRENT_SOURCE_DIR}/../../../XAPI/SPDLog/1.8.5/lib)
link_directories(${CMAKE_CURRENT_SOURCE_DIR}/../../../XAPI/YAML-CPP/0.8.0/lib)

add_library(${MarketGateWay_Version} SHARED PyTdxMarketGateWay.cpp)
target_link_libraries(${MarketGateWay_Version} spdlog yaml-cpp)

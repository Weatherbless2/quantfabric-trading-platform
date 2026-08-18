cmake_minimum_required(VERSION 3.16)
project(ATPTrader)

set(CMAKE_CXX_FLAGS "-fPIC")
set(CMAKE_INCLUDE_CURRENT_DIR ON)
set(CMAKE_BUILD_TYPE "RelWithDebInfo")
set(CMAKE_CXX_STANDARD 17)

set(AppVersion 0.1.0)
set(APIVersion "ATPBridge 1.0.0")
set(TradeGateWay_Version ${PROJECT_NAME}_${AppVersion})

add_definitions(-DFMT_HEADER_ONLY)
add_definitions(-DFMTLOG_HEADER_ONLY)
add_definitions(-D_GLIBCXX_USE_CXX11_ABI=0)

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
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/../../TraderAPI)
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/../..)
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/../../../XAPI/FMTLogger/include)
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/../../../XAPI/parallel_hashmap)
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/../../../XAPI/YAML-CPP/0.8.0/include)

link_directories(${CMAKE_CURRENT_SOURCE_DIR}/../../../XAPI/YAML-CPP/0.8.0/lib)

add_library(${TradeGateWay_Version} SHARED ATPTradeGateWay.cpp)
target_link_libraries(${TradeGateWay_Version} pthread yaml-cpp)

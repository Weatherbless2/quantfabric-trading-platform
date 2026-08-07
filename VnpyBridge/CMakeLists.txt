find_package(Qt5 REQUIRED COMPONENTS Core Network)

set(CMAKE_AUTOMOC ON)

add_executable(XVnpyBridge_0.1.0
    main.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../XMonitor/HPPackClient.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../XMonitor/HPPackClient.h
)

target_include_directories(XVnpyBridge_0.1.0 PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../XMonitor
    ${CMAKE_CURRENT_SOURCE_DIR}/../Utils
    ${CMAKE_CURRENT_SOURCE_DIR}/../XAPI/HP-Socket/5.8.2/include
    ${CMAKE_CURRENT_SOURCE_DIR}/../XAPI/FMTLogger/include
)

target_compile_features(XVnpyBridge_0.1.0 PRIVATE cxx_std_17)
target_compile_definitions(XVnpyBridge_0.1.0 PRIVATE
    FMT_HEADER_ONLY
    FMTLOG_HEADER_ONLY
)

target_link_libraries(XVnpyBridge_0.1.0 PRIVATE
    Qt5::Core
    Qt5::Network
    ${CMAKE_CURRENT_SOURCE_DIR}/../XAPI/HP-Socket/5.8.2/lib/libhpsocket4c.a
    ${CMAKE_CURRENT_SOURCE_DIR}/../XAPI/FMTLogger/lib/libfmtlog.a
    ${CMAKE_CURRENT_SOURCE_DIR}/../XAPI/FMTLogger/lib/libfmt.a
    pthread
    dl
)

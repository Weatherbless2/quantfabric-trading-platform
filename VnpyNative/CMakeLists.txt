find_package(Python3 REQUIRED COMPONENTS Interpreter Development.Module)

execute_process(
    COMMAND ${Python3_EXECUTABLE} -m pybind11 --cmakedir
    OUTPUT_VARIABLE PYBIND11_CMAKE_DIR
    OUTPUT_STRIP_TRAILING_WHITESPACE
    RESULT_VARIABLE PYBIND11_RESULT
)

if(NOT PYBIND11_RESULT EQUAL 0)
    message(FATAL_ERROR "pybind11 is required; install VnpyMonitor/requirements.txt first")
endif()

list(PREPEND CMAKE_PREFIX_PATH "${PYBIND11_CMAKE_DIR}")
find_package(pybind11 CONFIG REQUIRED)

pybind11_add_module(quantfabric_native MODULE
    QuantFabricClient.cpp
    module.cpp
)

target_compile_features(quantfabric_native PRIVATE cxx_std_17)
target_include_directories(quantfabric_native PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../Utils
    ${CMAKE_CURRENT_SOURCE_DIR}/../XAPI/HP-Socket/5.8.2/include
)
target_link_libraries(quantfabric_native PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../XAPI/HP-Socket/5.8.2/lib/libhpsocket4c.a
    pthread
    dl
)

set_target_properties(quantfabric_native PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}
)

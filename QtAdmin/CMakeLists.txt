find_package(Qt5 REQUIRED COMPONENTS Widgets Network)

add_executable(QtAdmin_0.1.0
    main.cpp
    MainWindow.cpp
)

target_compile_features(QtAdmin_0.1.0 PRIVATE cxx_std_17)
target_link_libraries(QtAdmin_0.1.0 PRIVATE Qt5::Network Qt5::Widgets)

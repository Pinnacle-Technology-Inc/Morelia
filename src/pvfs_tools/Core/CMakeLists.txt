cmake_minimum_required(VERSION 3.10)
project(pvfs_wrapper)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Set build type to Release to match PVFS library
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

# Add compiler flags to handle DLL interface warnings
if(MSVC)
    add_compile_options(/wd4251)  # Disable warning about DLL interface for STL containers
    # Set runtime library to match PVFS library
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>DLL")
    # Set optimization level
    set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} /O2")
endif()

# Create the shared library
add_library(pvfs_wrapper SHARED
    pvfs_wrapper.cpp
#    mjpg_video_wrapper.cpp
)


# Set the output name of the DLL
set_target_properties(pvfs_wrapper PROPERTIES
    OUTPUT_NAME "pvfs_wrapper"
    BUILD_WITH_INSTALL_RPATH TRUE
    INSTALL_RPATH "\$ORIGIN"
)

# Find PVFS library
find_library(PVFS_LIBRARY
    NAMES pvfs
    PATHS ${CMAKE_SOURCE_DIR}  # Look in the source directory
    NO_DEFAULT_PATH
)

if(NOT PVFS_LIBRARY)
    message(FATAL_ERROR "PVFS library not found. Please ensure pvfs.dll is in the source directory.")
endif()

# Link against the PVFS library and Qt
target_link_libraries(pvfs_wrapper PRIVATE 
    ${PVFS_LIBRARY}
)

# Copy PVFS DLL to build directory
add_custom_command(TARGET pvfs_wrapper POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        ${PVFS_LIBRARY}
        $<TARGET_FILE_DIR:pvfs_wrapper>
) 
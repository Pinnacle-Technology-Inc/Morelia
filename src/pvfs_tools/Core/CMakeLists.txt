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
    # Add BUILDING_PVFS_DLL define for pvfs.dll
    add_compile_definitions(BUILDING_PVFS_DLL)
    # Suppress CRT secure warnings for _open, strcpy, etc. (code is cross-platform)
    add_compile_definitions(_CRT_SECURE_NO_WARNINGS)
    # All DLLs and import libs in one directory so pvfs_wrapper can find pvfs.lib when linking
    set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}/Release")
    set(CMAKE_LIBRARY_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}/Release")
    set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}/Release")
    set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_DEBUG "${CMAKE_BINARY_DIR}/Debug")
    set(CMAKE_LIBRARY_OUTPUT_DIRECTORY_DEBUG "${CMAKE_BINARY_DIR}/Debug")
    set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY_DEBUG "${CMAKE_BINARY_DIR}/Debug")
endif()

# Build pvfs.dll first
add_library(pvfs SHARED
    pvfs.cpp
)

# When building pvfs.dll, define PVFS_LIBRARY so pvfs_global.h sets PVFS_EXPORT=dllexport (generates pvfs.lib).
if(MSVC)
    target_compile_definitions(pvfs PRIVATE PVFS_LIBRARY)
endif()

# Set the output name of the pvfs DLL (output dirs already set globally for MSVC above)
set_target_properties(pvfs PROPERTIES
    OUTPUT_NAME "pvfs"
    BUILD_WITH_INSTALL_RPATH TRUE
    INSTALL_RPATH "\$ORIGIN"
)

# Create the wrapper shared library
add_library(pvfs_wrapper SHARED
    pvfs_wrapper.cpp
#    mjpg_video_wrapper.cpp
)

# Set the output name of the wrapper DLL
set_target_properties(pvfs_wrapper PROPERTIES
    OUTPUT_NAME "pvfs_wrapper"
    BUILD_WITH_INSTALL_RPATH TRUE
    INSTALL_RPATH "\$ORIGIN"
)

# Link wrapper against the PVFS library. MSVC generator emits "Release\pvfs.lib"; add build dir
# so the linker finds pvfs.lib (needed when linking from a different cwd).
if(MSVC)
    target_link_directories(pvfs_wrapper PRIVATE "${CMAKE_BINARY_DIR}")
endif()
target_link_libraries(pvfs_wrapper PRIVATE pvfs)
add_dependencies(pvfs_wrapper pvfs)

# Copy PVFS DLL to build directory
add_custom_command(TARGET pvfs_wrapper POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        $<TARGET_FILE:pvfs>
        $<TARGET_FILE_DIR:pvfs_wrapper>
) 
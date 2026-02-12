#!/usr/bin/env bash
# Build PVFS native libraries on Linux or WSL.
# Produces libpvfs.so and libpvfs_wrapper.so in this directory (Core/).
# Requires: cmake, C++17 compiler (e.g. g++, clang++).

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
BUILD_DIR="${SCRIPT_DIR}/build_linux"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"
cmake -DCMAKE_BUILD_TYPE=Release ..
cmake --build .
# Copy built .so files into Core so pvfs_binding.py can load them
cp -f libpvfs.so libpvfs_wrapper.so "$SCRIPT_DIR/"
echo "Done. Copied libpvfs.so and libpvfs_wrapper.so to $SCRIPT_DIR"

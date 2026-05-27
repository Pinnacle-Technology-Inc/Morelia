#!/usr/bin/env bash
set -euo pipefail

echo "Updating package lists..."
sudo apt update

echo "Installing required system packages..."
sudo apt install -y \
    python3 \
    python3-venv \
    python3-dev \
    build-essential \
    pkg-config \
    libgl1 \
    libegl1 \
    libxkbcommon-x11-0 \
    libxcb-xinerama0 \
    libxcb1 \
    libx11-xcb1 \
    libxrender1 \
    libxi6 \
    libsm6 \
    libxext6 \
    libusb-1.0-0 \
    libusb-1.0-0-dev \
    libftdi1 \
    libftdi1-dev

echo "System dependencies installed."
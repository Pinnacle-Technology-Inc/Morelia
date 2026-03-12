# Morelia

<!DOCTYPE html>
<html lang="en">
   <div style="text-align: center;">
      <img src="docs/legacy/Logos/Rings.png" alt="logo" width="160"/></center>
   </div>
</html>


## Introduction 

![GitHub license](https://img.shields.io/github/license/Pinnacle-Technology-Inc/Python-POD-API)
![GitHub repo size](https://img.shields.io/github/repo-size/Pinnacle-Technology-Inc/Python-POD-API)
![GitHub issues](https://img.shields.io/github/issues-raw/Pinnacle-Technology-Inc/Python-POD-API)
![GitHub pull requests](https://img.shields.io/github/issues-pr-raw/Pinnacle-Technology-Inc/Python-POD-API)
![GitHub last commit](https://img.shields.io/github/last-commit/Pinnacle-Technology-Inc/Python-POD-API)
![GitHub commit activity](https://img.shields.io/github/commit-activity/m/Pinnacle-Technology-Inc/Python-POD-API)

Morelia is a free, open-source Python application programming interface (API) for Pinnacle Technology, Inc. data acquisition POD devices. Morelia core modules, usage examples, and supporting documentation can be found here on GitHub and are available freely under the New BSD License. 

Currently, the API supports 8206-HR, 8401-HR, 8229, 8480-SC, and 8274-D POD devices. In the future, we will offer support to other Pinnacle devices. 

You can find extensive documentation for the package [here](https://pinnacle-technology-inc.github.io/Morelia).

## Installation

Create and activate a virtual environment, then install with pip:

- **Windows:** `python -m venv venv` then `venv\Scripts\activate`
- **Linux / WSL:** `python3 -m venv venv` then `source venv/bin/activate`

Then run:

```bash
pip install ptech-morelia
```

To install from a local clone: `pip install .`

### Live plotting (optional)

Live EEG-style plotting requires Qt libraries that are not included in the base install. To add plotting support:

```bash
pip install ptech-morelia[plot]
```

This installs `pyqtgraph` and a Qt binding (PyQt5 on Windows/macOS/x86_64 Linux, PyQt6 on ARM Linux).

| Platform | Install command | Notes |
|---|---|---|
| Windows / macOS | `pip install ptech-morelia[plot]` | Works out of the box |
| Ubuntu / Debian / WSL | `bash install_ubuntu.sh && pip install ptech-morelia[plot]` | System libraries needed first |
| ARM Linux (RPi, etc.) | See conda instructions below | pip may fail to build Qt |

**Ubuntu / Debian / WSL:** Run `install_ubuntu.sh` before installing the plot extra to get the required system libraries. If the plotting examples (e.g. `8206_plot_stream.py`) still fault after that, install the xcb libraries:

```bash
sudo apt install libxcb-xinerama0 libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0
```

With WSLg (WSL 2), the plot window will appear on your Windows desktop. Older versions of WSL do not support graphics — in that case, use the non-plot examples.

**ARM Linux or other platforms where pip cannot build Qt:** Use conda to install the Qt stack, then pip for Morelia:

```bash
conda create -n morelia python=3.11
conda activate morelia
conda install -c conda-forge pyqtgraph pyqt numpy
pip install ptech-morelia
```

All non-plotting features (streaming, file recording, data conversion, etc.) work without the plot extra installed.

### PVFS native libraries

PVFS support uses bundled native libraries for Windows and Linux (including WSL); no separate compilation step is needed for standard installs.

If you are developing or building from source on Linux/WSL and the `.so` files are incompatible, you can build them from `src/pvfs_tools/Core/`:

```bash
cd src/pvfs_tools/Core
./build_linux.sh
```

Requires `cmake` and a C++17 compiler (e.g. `g++`).


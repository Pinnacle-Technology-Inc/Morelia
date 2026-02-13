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

PVFS support uses bundled native libraries for Windows and Linux (including WSL); no separate compilation step is needed for standard installs.

If you are developing or building from source on Linux/WSL and the `.so` files are missing, you can build them from `src/pvfs_tools/Core/`:

```bash
cd src/pvfs_tools/Core
./build_linux.sh
```

Requires `cmake` and a C++17 compiler (e.g. `g++`).

**Linux / WSL – plot window (PyQt5):** If you use the plotting examples (e.g. `8206_plot_stream.py`) and get a Qt/xcb plugin error, install the xcb system libraries. On Debian/Ubuntu/WSL:

```bash
sudo apt install libxcb-xinerama0 libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0
```

With WSLg (WSL 2), the plot window will then appear on your Windows desktop.


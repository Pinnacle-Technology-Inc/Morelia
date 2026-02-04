# D2XX Direct USB Communication Setup

This guide explains how to use FTDI D2XX direct USB communication instead of COM port communication for better performance and reliability.

**Diagnostic:** To verify your Python/PowerShell D2XX setup (library, drivers, device list, open, and read timeout), run:
```bash
python examples/d2xx_diagnostic.py
```
This checks that ftd2xx is available, devices are listed, the device opens, and reads respect the timeout (so the app does not hang).

## Dependencies

You need **one** of the following options, depending on your platform:

### Option 1: Windows (Recommended)

**Python Library:**
```bash
pip install ftd2xx
```

Or install via optional dependencies:
```bash
pip install ptech-morelia[d2xx-windows]
# or
pip install ptech-morelia[d2xx]  # Installs platform-appropriate library
```

**System Drivers:**
- Download and install **FTDI D2XX drivers** from: https://ftdichip.com/drivers/d2xx-drivers/
- Choose the appropriate driver for your Windows version (32-bit or 64-bit)
- After installation, the `FTD2XX.dll` should be available on your system

**Note:** The `ftd2xx` Python library wraps the official FTDI D2XX DLL, so you must have the drivers installed.

**D2XX configuration:** The Morelia D2XX path uses **115200 baud** and **RTS/CTS hardware flow control** by default when you pass `baudrate=115200` to the POD device (e.g. in `d2xx_example.py`). This is set in `D2XXComm` when opening the device.

### Option 2: Linux/Mac

**Python Library:**
```bash
pip install pylibftdi
```

Or install via optional dependencies:
```bash
pip install ptech-morelia[d2xx-linux]
# or
pip install ptech-morelia[d2xx]  # Installs platform-appropriate library
```

**System Library:**
- Install `libftdi` library:
  - **Ubuntu/Debian:** `sudo apt-get install libftdi1-dev`
  - **Fedora/RHEL:** `sudo dnf install libftdi-devel`
  - **macOS:** `brew install libftdi`

**Note:** `pylibftdi` uses the open-source `libftdi` library, not the official FTDI drivers.

### Option 3: WSL (Windows Subsystem for Linux)

**Important:** WSL has limited USB device support. For reliable D2XX communication in WSL:

1. **Use USB passthrough:** WSL2 supports USB passthrough via `usbipd-win` (Windows) and `usbip` (Linux). However, this adds complexity and may not work reliably for FTDI devices.

2. **Recommended approach:** Use native Windows with `ftd2xx` instead of WSL for D2XX communication. The Windows D2XX implementation is more mature and reliable.

3. **If you must use WSL:**
   - Install `pylibftdi` in WSL: `pip install pylibftdi`
   - Install `libftdi` in WSL: `sudo apt-get install libftdi1-dev`
   - Set up USB passthrough (see WSL USB documentation)
   - Configure udev rules: `sudo nano /etc/udev/rules.d/99-ftdi.rules` with:
     ```
     SUBSYSTEM=="usb", ATTRS{idVendor}=="0403", MODE="0666"
     ```
   - Reload udev: `sudo udevadm control --reload-rules && sudo udevadm trigger`

**Note:** Native Linux installations work better than WSL for D2XX. Consider using a native Linux system or Windows for production use.

## Finding Your Device

Before using D2XX, you need to identify your device:

### Using ftd2xx (Windows):

```python
import ftd2xx as ftd

# List all devices
num_devices = ftd.createDeviceInfoList()
for i in range(num_devices):
    info = ftd.getDeviceInfoDetail(i)
    print(f"Index {i}: {info['serial']} - {info['description']}")
```

### Using pylibftdi (Linux/Mac):

```python
from pylibftdi import Driver

driver = Driver()
devices = driver.list_devices()
for idx, (manufacturer, description, serial) in enumerate(devices):
    print(f"Index {idx}: {serial.decode('utf-8')} - {description.decode('utf-8')}")
```

### Using Morelia Helper:

```python
from Morelia.Devices.SerialPorts.d2xx_helpers import list_d2xx_devices

devices = list_d2xx_devices()
for dev in devices:
    print(f"Index {dev['index']}: {dev['serial']} - {dev['description']}")
```

## Usage Example

```python
from Morelia.Devices import Pod8206HR
from Morelia.Stream.sink import EDFSink
from Morelia.Stream.data_flow import DataFlow

# Option 1: Use device serial number (recommended)
pod = Pod8206HR('FT123456', 100, use_d2xx=True)

# Option 2: Use device index
pod = Pod8206HR(0, 100, use_d2xx=True)  # First device

# Option 3: Use COM port name (less reliable - tries to match by index)
pod = Pod8206HR('COM9', 100, use_d2xx=True)

# Rest of your code...
edf_sink = EDFSink('output.edf', pod)
mapping = [(pod, [edf_sink])]
flowgraph = DataFlow(mapping)
flowgraph.collect_for_seconds(60)
```

## Troubleshooting

### Error: "libftdi library not found"
- **Windows:** Install FTDI D2XX drivers from FTDI website, or use `pip install ftd2xx`
- **Linux/Mac:** Install libftdi library via package manager

### Error: "No D2XX library available"
- Install either `ftd2xx` (Windows) or `pylibftdi` (Linux/Mac)
- Ensure system drivers/libraries are installed

### Device not found
- Make sure the device is connected
- Check that no other program is using the device
- Try using the device index instead of serial number
- On Windows, ensure FTDI D2XX drivers are installed (not just VCP drivers)

## Benefits of D2XX

- **Better Performance:** Direct USB communication bypasses OS serial layer
- **Lower Latency:** Fewer layers between your code and device
- **More Reliable:** Less prone to timeouts and buffer issues
- **Better Error Handling:** Direct access to USB status

## Fallback to COM Port

If D2XX is not available or fails, you can always fall back to COM port communication:

```python
pod = Pod8206HR('COM9', 100, use_d2xx=False)  # or omit use_d2xx parameter
```

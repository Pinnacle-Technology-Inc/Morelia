# D2XX Direct USB Communication Setup

This guide explains native FTDI D2XX access and the dashboard's connection selection. Native USB access bypasses the COM-port API; performance and reliability must be measured on your hardware.

## Vue dashboard

The dashboard supports a separate **Connection** setting on each configured 8206HR or 8401HR device:

- **VCP:** use its current COM port, matched by exact FTDI serial.
- **D2XX:** use the official native driver and exact serial; a COM port is not required.
- **Auto:** prefer VCP when both interfaces exist. During discovery, a failed VCP probe can fall back to D2XX after its handle closes. Busy devices, permission failures, and incomplete cleanup block fallback. Run startup resolves the preferred available endpoint and keeps that transport for recovery.

Existing configurations without a connection setting retain VCP behavior. New dashboard configurations offer Auto. Selecting D2XX explicitly is how to use native USB while leaving VCP enabled in Windows. Both interfaces represent one device row, not two independent devices. Connection settings are separate from acquisition templates.

Windows sometimes reports an FT232R/FT245R VCP serial with an extra channel suffix while D2XX reports the USB serial. The dashboard first compares the VCP endpoint with an observed USB base serial and the chip's supported channel suffix (A for single-channel, A/B for dual-channel, A–D for quad-channel devices). It falls back to a unique Windows ContainerID relationship for single-channel devices. Missing or contradictory evidence is never permission to trim a serial. Separate channels retain distinct identities, existing saved IDs are preserved, and exact native serials remain the open addresses. One indexed registry snapshot is used per discovery scan. This identity handling does not expand the supported POD acquisition models.

If an FTDI endpoint is already open, the native driver may omit its serial and other identifying fields. The dashboard reports **busy, identity unavailable**, keeps the anonymous entry visible, and skips probing. Close the connection holding that endpoint and rescan; the next inventory can report its identity after release. An enumeration index or an unmatched saved device is never used to guess the missing serial.

In the backend Python environment on Windows, install:

```powershell
python -m pip install -e ".[hardware,d2xx]"
pinnacle doctor
```

Run the install from `vue-dashboard/backend`. Install the matching official FTDI Windows driver separately. The doctor's native-library line does not open a device and is not proof of acquisition compatibility. The Python wrapper and DLL must match the Python architecture.

Use **Scan Devices**, configure the device's connection and baud rate, then start a run. Scans enumerate both interfaces and acquire a physical-device lease before issuing identification commands. A claimed device is not actively probed. Scan warnings distinguish missing native dependencies and enumeration failures from zero connected devices.

You can also show or change a free device's connection without changing its template:

```powershell
pinnacle device connection 12
pinnacle device connection 12 --transport d2xx --baudrate 115200
pinnacle device connection 12 --transport vcp
```

Use the baud rate and flow control appropriate for the device. D2XX does not inherently mean 115200 baud. The existing SDK defaults to 9600; the example below explicitly requests 115200. Newly discovered native devices use bounded identification attempts at these documented rates; saved configurations use their saved rate. VCP defaults to no hardware flow control; native D2XX defaults to RTS/CTS unless explicitly configured otherwise.

A run records the selected transport, driver, identity, and settings in its manifest. Recovery uses that same transport and identity; it does not silently switch between VCP and D2XX. A device's COM number can change without changing its identity. Stop the run before changing connection settings.

Dashboard transport code lives in the backend: `app/discovery/ftdi_transport.py` owns native/VCP I/O and `app/discovery/managed_pods.py` adapts the original SDK models. Scans enter through `pod_scan`; runtime workers use the same adapters. No SDK device-file changes are required. Dashboard command queues are passed directly to spawned workers, so they do not allocate or discover TCP queue-server ports. Restart the backend and its workers after upgrading.

Native dashboard support targets Windows with `ftd2xx`, for the 8206HR and 8401HR. Other discovered models are not automatically enabled for acquisition. The library's Linux/macOS `pylibftdi` path below is a separate backend and is not equivalent to Windows native qualification. Software tests cover policy and driver contracts; live acquisition, rates, and unplug/replug still need validation on your devices.

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

**D2XX configuration:** The standalone SDK example explicitly requests **115200 baud**. Dashboard flow control is configured through the device connection API or CLI; the original SDK constructors do not accept the dashboard's additional connection keywords.

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

# Standalone SDK example; dashboard adapters are owned by the backend.
pod = Pod8206HR('FT123456', 100, use_d2xx=True, baudrate=115200)

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
- Check the exact serial, including leading zeros, case, and channel suffix
- Blank or duplicate serials require explicit hardware identification; do not guess by enumeration index
- On Windows, ensure FTDI D2XX drivers are installed (not just VCP drivers)

## Driver coexistence

Windows FTDI CDM can expose both VCP and D2XX. A COM port's presence does not mean the native interface is absent. Applications must not communicate through both interfaces at the same time. Native serials are not COM numbers; never convert `COM3` into FTDI device index 3. See [FTDI's driver documentation](https://www.ftdichip.com/Support/Knowledgebase/2000installingftdidevicedriver.htm).

## Fallback to COM Port

If a VCP interface is available, stop the current run and explicitly select VCP to use it. The dashboard does not switch interfaces after a native error:

```python
pod = Pod8206HR('COM9', 100, use_d2xx=False)  # or omit use_d2xx parameter
```

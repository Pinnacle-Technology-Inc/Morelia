"""Example script showing how to use D2XX direct USB communication with POD devices.

This example demonstrates how to use FTDI D2XX drivers instead of COM port communication
for better performance and reliability.

Requirements (choose one based on your platform):
    Windows:
        pip install ftd2xx
        Install FTDI D2XX drivers from: https://ftdichip.com/drivers/d2xx-drivers/
    
    Linux/Mac:
        pip install pylibftdi
        Install libftdi library (e.g., sudo apt-get install libftdi1-dev)
        
See docs/D2XX_SETUP.md for detailed setup instructions.
"""

from Morelia.Devices import Pod8206HR
from Morelia.Stream.sink import EDFSink
from Morelia.Stream.data_flow import DataFlow

# Helper function to list available D2XX devices
def list_d2xx_devices():
    """List all available FTDI D2XX devices."""
    try:
        from Morelia.Devices.SerialPorts.d2xx_helpers import list_d2xx_devices
        devices = list_d2xx_devices()
        print("Available D2XX devices:")
        for dev in devices:
            print(f"  Index {dev['index']}: {dev['description']} (Serial: {dev['serial']})")
        return devices
    except ImportError:
        print("D2XX support not available. Install pylibftdi: pip install pylibftdi")
        return []

if __name__ == "__main__":
    # First, list available D2XX devices to find your device
    devices = list_d2xx_devices()
    
    if not devices:
        print("\nNo D2XX devices found or D2XX not available.")
        print("Falling back to COM port communication...")
        use_d2xx = False
        port = 'COM9'  # Use your COM port here
    else:
        # Use the first device's serial number (or use index: 0, 1, 2, etc.)
        # You can also use the device description
        device_serial = devices[0]['serial']
        # Handle bytes to string conversion if needed
        if isinstance(device_serial, bytes):
            device_serial = device_serial.decode('utf-8')
        print(f"\nUsing D2XX device: {device_serial}")
        use_d2xx = True
        port = device_serial  # Use serial number for D2XX
    
    # Create POD device with D2XX enabled
    # Option 1: Use serial number
    # pod_1 = Pod8206HR(device_serial, 100, use_d2xx=True)
    
    # Option 2: Use device index (0, 1, 2, etc.)
    # pod_1 = Pod8206HR(0, 100, use_d2xx=True)
    
    # Option 3: Use COM port name (will try to match to D2XX device by index)
    # This is less reliable - better to use serial number
    # D2XX uses 115200 baud with RTS/CTS handshake (configured in D2XXComm)
    pod_1 = Pod8206HR(port, 100, use_d2xx=use_d2xx, baudrate=115200)
    
    # Create EDF sink
    edf_dump_1 = EDFSink('dump_1_d2xx.edf', pod_1)
    
    # Create mapping and flowgraph
    mapping = [(pod_1, [edf_dump_1])]
    flowgraph = DataFlow(mapping)
    
    # Collect data for 60 seconds
    print("Starting data collection with D2XX...", flush=True)
    flowgraph.collect_for_seconds(60)

    # Clean up
    if hasattr(pod_1, "_port"):
        pod_1._port = None
    
    print("Data collection complete!")

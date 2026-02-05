"""Helper functions for working with FTDI D2XX devices."""

# Try ftd2xx first (Windows with official FTDI drivers)
try:
    import ftd2xx as ftd
    FTD2XX_AVAILABLE = True
except ImportError:
    FTD2XX_AVAILABLE = False
    ftd = None

# Fall back to pylibftdi (Linux/Mac with libftdi)
try:
    from pylibftdi import Driver
    PYLIBFTDI_AVAILABLE = True
except ImportError:
    PYLIBFTDI_AVAILABLE = False
    Driver = None

D2XX_AVAILABLE = FTD2XX_AVAILABLE or PYLIBFTDI_AVAILABLE


def list_d2xx_devices():
    """
    List all available FTDI D2XX devices.
    
    Returns:
        list: List of dictionaries with device information:
            - index: Device index
            - serial: Serial number
            - description: Device description
            - manufacturer: Manufacturer string
    """
    if not D2XX_AVAILABLE:
        error_msg = (
            "No D2XX library available. Install one of the following:\n"
            "  Windows: pip install ftd2xx (requires FTDI D2XX drivers from FTDI website)\n"
            "  Linux/Mac: pip install pylibftdi (requires libftdi library)\n"
        )
        raise ImportError(error_msg)
    
    devices = []
    
    if FTD2XX_AVAILABLE:
        # Use ftd2xx library
        try:
            num_devices = ftd.createDeviceInfoList()
            for idx in range(num_devices):
                try:
                    # getDeviceInfoDetail returns a tuple or dict depending on version
                    info = ftd.getDeviceInfoDetail(idx)
                    if isinstance(info, dict):
                        devices.append({
                            'index': idx,
                            'serial': info.get('serial', ''),
                            'description': info.get('description', ''),
                            'manufacturer': info.get('manufacturer', 'FTDI')
                        })
                    elif isinstance(info, tuple):
                        # Handle tuple format: (flags, type, id, loc_id, serial, description, handle)
                        devices.append({
                            'index': idx,
                            'serial': info[4] if len(info) > 4 else '',
                            'description': info[5] if len(info) > 5 else '',
                            'manufacturer': 'FTDI'
                        })
                except Exception as e:
                    # Skip devices that can't be queried
                    print(f"Warning: Could not get info for device {idx}: {e}")
                    continue
        except Exception as e:
            raise Exception(f"Error listing ftd2xx devices: {e}. Make sure FTDI D2XX drivers are installed.")
    elif PYLIBFTDI_AVAILABLE:
        # Use pylibftdi library
        try:
            driver = Driver()
            device_list = driver.list_devices()
            
            for idx, (manufacturer, description, serial) in enumerate(device_list):
                devices.append({
                    'index': idx,
                    'serial': serial.decode('utf-8') if serial else None,
                    'description': description.decode('utf-8') if description else None,
                    'manufacturer': manufacturer.decode('utf-8') if manufacturer else None
                })
        except Exception as e:
            raise Exception(f"Error listing pylibftdi devices: {e}")
    
    return devices


def find_d2xx_device_by_serial(serial_number: str):
    """
    Find a D2XX device by its serial number.
    
    Args:
        serial_number: Serial number to search for.
        
    Returns:
        dict | None: Device information if found, None otherwise.
    """
    devices = list_d2xx_devices()
    for device in devices:
        if device['serial'] == serial_number:
            return device
    return None


def find_d2xx_device_by_com_port(com_port: str):
    """
    Attempt to find a D2XX device that corresponds to a COM port.
    
    Note: This is a best-effort approach. COM ports and D2XX devices don't
    have a direct 1:1 mapping. This function lists devices and you'll need
    to manually match them.
    
    Args:
        com_port: COM port name (e.g., "COM9").
        
    Returns:
        list: List of available D2XX devices (user must select the correct one).
    """
    return list_d2xx_devices()

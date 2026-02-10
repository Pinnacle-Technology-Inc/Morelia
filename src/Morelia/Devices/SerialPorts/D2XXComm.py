"""FTDI D2XX direct USB communication interface.

This module provides a D2XX-based communication class that can be used as a drop-in
replacement for PortIO, providing direct USB communication instead of COM port communication.

Requirements (choose one):
    Option 1 (Windows - Recommended):
        - ftd2xx: pip install ftd2xx
        - FTDI D2XX drivers installed (download from FTDI website)
    
    Option 2 (Linux/Mac):
        - pylibftdi: pip install pylibftdi
        - libftdi library installed (usually via package manager)

Author: Auto-generated
"""

import platform
import time
from typing import Optional

# Try ftd2xx first (better for Windows with official FTDI drivers)
try:
    import ftd2xx as ftd
    FTD2XX_AVAILABLE = True
except ImportError:
    FTD2XX_AVAILABLE = False
    ftd = None

# Fall back to pylibftdi (better for Linux, requires libftdi)
try:
    from pylibftdi import Device, Driver, FtdiError
    PYLIBFTDI_AVAILABLE = True
except ImportError:
    PYLIBFTDI_AVAILABLE = False
    Device = None
    Driver = None
    FtdiError = Exception

D2XX_AVAILABLE = FTD2XX_AVAILABLE or PYLIBFTDI_AVAILABLE


class D2XXPortIO:
    """
    D2XX-based USB communication handler that provides the same interface as PortIO.
    Uses FTDI D2XX drivers for direct USB communication, bypassing the OS COM port layer.
    
    This can provide better performance, lower latency, and more reliable communication
    compared to COM port communication.

    Attributes:
        _device (Device): Instance-level FTDI D2XX device.
        port: Port identifier (serial number, description, or index).
        baudrate: Baud rate for communication.
    """

    def __init__(self, port: str | int, baudrate: int = 9600) -> None:
        """Initialize D2XX device connection.

        Args:
            port: Can be:
                - Serial number (str): e.g., "FT123456"
                - Device description (str): e.g., "FT232H"
                - Device index (int): 0, 1, 2, etc.
                - COM port name (str): Will attempt to find matching D2XX device
            baudrate: Baud rate for communication. Defaults to 9600.
        """
        if not D2XX_AVAILABLE:
            error_msg = (
                "No D2XX library available. Install one of the following:\n"
                "  Windows: pip install ftd2xx (requires FTDI D2XX drivers from FTDI website)\n"
                "  Linux/Mac: pip install pylibftdi (requires libftdi library)\n"
            )
            raise ImportError(error_msg)
        
        # Determine which library to use (prefer ftd2xx on Windows)
        self._use_ftd2xx = FTD2XX_AVAILABLE and (platform.system() == 'Windows' or not PYLIBFTDI_AVAILABLE)
        self._use_pylibftdi = PYLIBFTDI_AVAILABLE and not self._use_ftd2xx

        self.port = port
        self.baudrate = baudrate
        self._device = None  # Can be ftd2xx device or pylibftdi Device
        self._ftd2xx_handle = None  # For ftd2xx library
        # Cache last setTimeouts so we don't call it on every read() during streaming
        self._cached_timeouts: tuple[int, int] | None = None  # (read_ms, write_ms)

        if port == 'TEST':
            # For testing, we could use a mock or raise an error
            raise NotImplementedError("TEST mode not supported for D2XX")
        else:
            self.open_serial_port(port, baudrate=baudrate)

    def __del__(self) -> None:
        """Cleanup: close the device when object is destroyed."""
        self.close_serial_port()

    @staticmethod
    def is_port_in_use(port: str) -> bool:
        """
        Check if a D2XX device is in use.
        
        Note: D2XX devices are identified by serial number, description, or index,
        not COM port names. This method attempts to find the device and check if it's open.
        """
        if not D2XX_AVAILABLE:
            return False
        
        try:
            # Try to open the device to see if it's available
            device = Device(device_id=str(port))
            device.close()
            return False  # Device is available
        except (FtdiError, Exception):
            return True  # Device is in use or doesn't exist

    @staticmethod
    def build_port_name(port: str | int) -> str:
        """Convert port identifier to string format for D2XX.
        
        D2XX uses serial numbers, descriptions, or indices, not COM port names.
        This method converts the input to a string that can be used with D2XX.
        
        For best results, use the device's serial number directly.
        You can list available devices using list_d2xx_devices() from d2xx_helpers.
        """
        if isinstance(port, int):
            return str(port)  # Device index
        elif isinstance(port, str):
            # If it's a COM port name, try to extract index (not reliable)
            # Better to use serial number directly
            if port.startswith('COM') or port.startswith('/dev/tty'):
                # Try to use as index - this is a best guess
                try:
                    num = int(''.join(filter(str.isdigit, port)))
                    return str(num)
                except ValueError:
                    # If we can't extract a number, return as-is
                    # User should use serial number instead
                    return port
            else:
                return port  # Assume it's a serial number or description
        return str(port)
    
    @staticmethod
    def list_devices():
        """List all available D2XX devices.
        
        Returns:
            list: List of device information dictionaries.
        """
        from Morelia.Devices.SerialPorts.d2xx_helpers import list_d2xx_devices
        return list_d2xx_devices()

    def is_serial_open(self) -> bool:
        """Check if the D2XX device is open.

        Returns:
            bool: True if device is open, False otherwise.
        """
        if self._use_ftd2xx:
            return self._ftd2xx_handle is not None
        else:
            return self._device is not None

    def is_serial_closed(self) -> bool:
        """Check if the D2XX device is closed.

        Returns:
            bool: True if device is closed, False otherwise.
        """
        return not self.is_serial_open()

    def close_serial_port(self) -> None:
        """Close the D2XX device if open."""
        if self._use_ftd2xx:
            if self._ftd2xx_handle is not None:
                try:
                    self._ftd2xx_handle.close()
                except Exception:
                    pass
                finally:
                    self._ftd2xx_handle = None
            self._cached_timeouts = None
        else:
            if self._device is not None:
                try:
                    self._device.close()
                except Exception:
                    pass
                finally:
                    self._device = None

    def open_serial_port(self, port: str | int, baudrate: int = 9600) -> None:
        """Open a D2XX device.

        Args:
            port: Device identifier (serial number, description, or index).
            baudrate: Baud rate for communication.

        Raises:
            Exception: If device cannot be opened.
        """
        # Close current device if open
        if self.is_serial_open():
            self.close_serial_port()

        self.baudrate = baudrate
        port_id = self.build_port_name(port)

        try:
            if self._use_ftd2xx:
                # Use ftd2xx library (Windows with official FTDI drivers)
                try:
                    # Always enumerate and match by serial/description first so that a numeric
                    # serial (e.g. "12345") is not mistaken for device index.
                    num_devices = ftd.createDeviceInfoList()
                    port_id_str = str(port_id)
                    opened = False
                    for i in range(num_devices):
                        info = ftd.getDeviceInfoDetail(i)
                        # getDeviceInfoDetail may return dict or tuple; handle both
                        if isinstance(info, dict):
                            dev_serial = info.get('serial', '')
                            dev_desc = info.get('description', '')
                        elif isinstance(info, tuple):
                            # Tuple format: (flags, type, id, loc_id, serial, description, ...)
                            dev_serial = info[4] if len(info) > 4 else ''
                            dev_desc = info[5] if len(info) > 5 else ''
                        else:
                            continue
                        # Normalize to string for comparison (serial/desc may be bytes)
                        if isinstance(dev_serial, bytes):
                            dev_serial = dev_serial.decode('utf-8', errors='replace')
                        if isinstance(dev_desc, bytes):
                            dev_desc = dev_desc.decode('utf-8', errors='replace')
                        if dev_serial == port_id_str or dev_desc == port_id_str:
                            self._ftd2xx_handle = ftd.open(i)
                            opened = True
                            break
                    if not opened:
                        # Fall back to index only when port is explicitly an int or a small index string (0–31)
                        if isinstance(port, int):
                            idx = port
                            if 0 <= idx < num_devices:
                                self._ftd2xx_handle = ftd.open(idx)
                                opened = True
                        elif isinstance(port_id, str) and port_id.isdigit():
                            idx = int(port_id)
                            if 0 <= idx < num_devices and idx <= 31:
                                self._ftd2xx_handle = ftd.open(idx)
                                opened = True
                        if not opened:
                            raise Exception(
                                f'No D2XX device found with serial or description "{port_id}". '
                                f'Use list_d2xx_devices() to see available devices and use index (e.g. 0) or serial.'
                            )
                except Exception as e:
                    raise Exception(f'Failed to open D2XX device {port_id} with ftd2xx: {e}')
                
                # Set baudrate and configure for 8N1
                # Note: ftd2xx API may vary - adjust if needed
                try:
                    # Try standard ftd2xx API
                    self._ftd2xx_handle.setBaudRate(baudrate)
                    # Constants: 8 data bits, 0 stop bits (means 1), 0 parity (none)
                    self._ftd2xx_handle.setDataCharacteristics(8, 0, 0)
                    # RTS/CTS hardware flow control (FT_FLOW_RTS_CTS = 256; xon/xoff unused)
                    try:
                        rts_cts = getattr(ftd, 'FT_FLOW_RTS_CTS', 256)
                        self._ftd2xx_handle.setFlowControl(rts_cts, 0, 0)
                    except (AttributeError, TypeError):
                        pass  # Some builds may not have setFlowControl
                    # Set read/write timeouts so read() returns instead of blocking indefinitely
                    try:
                        self._ftd2xx_handle.setTimeouts(5000, 5000)  # read_ms, write_ms (5 sec)
                    except (AttributeError, TypeError):
                        pass  # Some builds may not have setTimeouts
                    self._ftd2xx_handle.purge()
                except AttributeError:
                    # Try alternative API if methods don't exist
                    try:
                        self._ftd2xx_handle.baudrate = baudrate
                        self._ftd2xx_handle.flush()
                    except AttributeError:
                        # If neither works, just set baudrate property if available
                        if hasattr(self._ftd2xx_handle, 'baudrate'):
                            self._ftd2xx_handle.baudrate = baudrate
                        
                time.sleep(0.1)
                
            else:
                # Use pylibftdi library (Linux/Mac with libftdi)
                try:
                    # Try to open by serial number/description first
                    try:
                        self._device = Device(device_id=port_id)
                    except FtdiError:
                        # If that fails, try by index
                        try:
                            idx = int(port_id)
                            self._device = Device(device_index=idx)
                        except (ValueError, FtdiError):
                            # Last resort: try as-is
                            self._device = Device(device_id=port_id)

                    # Set baudrate (pylibftdi defaults to 8N1 which is correct for POD protocol)
                    self._device.baudrate = baudrate
                    
                    # Purge buffers
                    self._device.flush()
                    
                    # Give device a moment to stabilize
                    time.sleep(0.1)

                except FtdiError as e:
                    raise Exception(f'Failed to open D2XX device {port_id} with pylibftdi: {e}')

        except Exception as e:
            raise Exception(f'Error opening D2XX device: {e}')

    def set_baudrate(self, baudrate: int) -> bool:
        """Set the baud rate of the D2XX device.

        Args:
            baudrate: Baud rate to set.

        Returns:
            bool: True if successful, False otherwise.
        """
        if not self.is_serial_open():
            return False
            
        try:
            if self._use_ftd2xx:
                try:
                    self._ftd2xx_handle.setBaudRate(baudrate)
                except AttributeError:
                    if hasattr(self._ftd2xx_handle, 'baudrate'):
                        self._ftd2xx_handle.baudrate = baudrate
                    else:
                        return False
            else:
                self._device.baudrate = baudrate
            self.baudrate = baudrate
            return True
        except Exception:
            return False

    def flush(self) -> bool:
        """Flush input and output buffers.

        Returns:
            bool: True if successful, False otherwise.
        """
        if not self.is_serial_open():
            return False

        try:
            if self._use_ftd2xx:
                try:
                    self._ftd2xx_handle.purge()
                except AttributeError:
                    try:
                        self._ftd2xx_handle.flush()
                    except AttributeError:
                        pass  # Some versions may not support purge/flush
            else:
                self._device.flush()
            return True
        except Exception:
            return False

    def purge_rx(self) -> bool:
        """Purge RX (receive) buffer only. Useful before starting to read a new packet.

        Returns:
            bool: True if successful, False otherwise.
        """
        if not self.is_serial_open():
            return False

        try:
            if self._use_ftd2xx:
                try:
                    self._ftd2xx_handle.purge(2)  # 2 = RX buffer only
                except (AttributeError, TypeError):
                    # Some builds may not support purge with flags, try without
                    try:
                        self._ftd2xx_handle.purge()
                    except AttributeError:
                        pass
            else:
                self._device.flush()  # pylibftdi flush clears both
            return True
        except Exception:
            return False

    def get_port_name(self) -> str | None:
        """Get the device identifier.

        Returns:
            str | None: Device serial number or description if open, None otherwise.
        """
        if not self.is_serial_open():
            return None
            
        try:
            if self._use_ftd2xx:
                try:
                    info = self._ftd2xx_handle.getDeviceInfo()
                    if isinstance(info, dict):
                        return info.get('serial', str(self.port))
                    else:
                        return str(self.port)
                except (AttributeError, Exception):
                    return str(self.port)
            else:
                return self._device.serial_number or str(self.port)
        except Exception:
            return str(self.port)

    def read(self, numBytes: int, timeout_sec: int | float = 5) -> bytes | None:
        """Read a specified number of bytes from the D2XX device.

        Args:
            numBytes: Number of bytes to read.
            timeout_sec: Timeout in seconds.

        Returns:
            bytes | None: Read bytes if successful, None if timeout or error.
        """
        if self.is_serial_closed():
            return None

        try:
            if self._use_ftd2xx:
                # Set device read timeout only when it changes (avoids thousands of setTimeouts/sec during streaming)
                read_ms = int(timeout_sec * 1000)
                write_ms = 5000
                if self._cached_timeouts != (read_ms, write_ms):
                    try:
                        self._ftd2xx_handle.setTimeouts(read_ms, write_ms)
                        self._cached_timeouts = (read_ms, write_ms)
                    except (AttributeError, TypeError):
                        pass

                # Note: Do NOT purge RX buffer here - read_pod_packet() calls read(1) multiple times
                # per packet, and purging between reads would clear the rest of the packet!
                # Purge is done once when opening the device in open_serial_port()

                # Simple direct read like raw ftd2xx - let the driver handle timeout
                # This matches the behavior in section [4] that works perfectly
                # Note: read() blocks until numBytes are received OR timeout expires
                # If timeout expires, returns b'' (empty bytes)
                data = self._ftd2xx_handle.read(numBytes)
                # Return data if we got any, None if empty (timeout)
                # Note: ftd2xx read() returns b'' on timeout, not None
                return data if data else None
            else:
                # pylibftdi read (non-blocking) - collect bytes in a loop
                start_time = time.time()
                data = b''
                while len(data) < numBytes and (time.time() - start_time) < timeout_sec:
                    chunk = self._device.read(numBytes - len(data))
                    if chunk:
                        data += chunk
                    else:
                        time.sleep(0.01)
                return data if data else None
        except Exception:
            return None

    def read_line(self) -> bytes | None:
        """Read until a newline character is encountered.

        Returns:
            bytes | None: Complete line if successful, None otherwise.
        """
        if self.is_serial_closed():
            return None

        line = b''
        timeout = 5.0
        start_time = time.time()
        
        while (time.time() - start_time) < timeout:
            try:
                if self._use_ftd2xx:
                    data = self._ftd2xx_handle.read(1)
                else:
                    data = self._device.read(1)
                    
                if data:
                    line += data
                    if b'\n' in line:
                        return line
                else:
                    time.sleep(0.01)
            except Exception:
                return None
        
        return None  # Timeout

    def read_until(self, eol: bytes) -> bytes | None:
        """Read until a specific end-of-line character is encountered.

        Args:
            eol: End-of-line bytes to search for.

        Returns:
            bytes | None: Data up to and including EOL if successful, None otherwise.
        """
        if self.is_serial_closed():
            return None

        data = b''
        timeout = 5.0
        start_time = time.time()
        
        while (time.time() - start_time) < timeout:
            try:
                if self._use_ftd2xx:
                    chunk = self._ftd2xx_handle.read(1)
                else:
                    chunk = self._device.read(1)
                    
                if chunk:
                    data += chunk
                    if eol in data:
                        return data
                else:
                    time.sleep(0.01)
            except Exception:
                return None
        
        return None  # Timeout

    def write(self, message: bytes) -> None:
        """Write data to the D2XX device.

        Args:
            message: Bytes to write.

        Raises:
            Exception: If write fails.
        """
        if not self.is_serial_open():
            raise Exception("Device is not open")
            
        try:
            if self._use_ftd2xx:
                # ftd2xx write() takes only the message bytes (not length)
                # Returns number of bytes written
                written = self._ftd2xx_handle.write(message)
                if written != len(message):
                    raise Exception(f'Partial write: {written}/{len(message)} bytes written')
                # Note: Don't purge TX buffer after write - that would clear the data we just sent!
                # The data is already queued and will be sent by the driver
            else:
                written = self._device.write(message)
                if written != len(message):
                    raise Exception(f'Partial write: {written}/{len(message)} bytes written')
        except Exception as e:
            raise Exception(f'D2XX write error: {e}')

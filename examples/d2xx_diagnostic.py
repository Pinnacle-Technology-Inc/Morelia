"""D2XX diagnostic script: verify Python/PowerShell D2XX setup and device communication.

Run from project root (or with PYTHONPATH including src):
    python examples/d2xx_diagnostic.py

This checks:
  1. Python version and platform
  2. ftd2xx (or pylibftdi) import and availability
  3. D2XX device list
  4. Open device, set baud rate and timeouts
  5. Read timeout behavior (device should return within timeout if no data)
  6. Optional: raw write/read test

Use this to confirm D2XX is correctly configured before running d2xx_example.py.
"""

import sys
import platform
import time

def _decode(b):
    """Decode serial/description from bytes or return as-is."""
    if isinstance(b, bytes):
        return b.decode("utf-8", errors="replace")
    return b

def main():
    print("=" * 60, flush=True)
    print("D2XX Diagnostic – Python/PowerShell environment check", flush=True)
    print("=" * 60, flush=True)

    # 1. Python and platform
    print(f"\n[1] Python: {sys.version}", flush=True)
    print(f"    Platform: {platform.system()} {platform.release()}", flush=True)

    # 2. ftd2xx / pylibftdi
    print("\n[2] D2XX library:", flush=True)
    ftd2xx_ok = False
    pylibftdi_ok = False
    try:
        import ftd2xx as ftd
        ftd2xx_ok = True
        ver = getattr(ftd, "getLibraryVersion", None)
        if callable(ver):
            print(f"    ftd2xx: OK (version: {ver()})", flush=True)
        else:
            print("    ftd2xx: OK (imported)", flush=True)
    except ImportError as e:
        print(f"    ftd2xx: NOT AVAILABLE ({e})", flush=True)

    if not ftd2xx_ok:
        try:
            from pylibftdi import Device, Driver
            pylibftdi_ok = True
            print("    pylibftdi: OK", flush=True)
        except ImportError as e:
            print(f"    pylibftdi: NOT AVAILABLE ({e})", flush=True)

    if not ftd2xx_ok and not pylibftdi_ok:
        print("\n    Install with: pip install ptech-morelia[d2xx]", flush=True)
        return 1

    # 3. List devices (ftd2xx path)
    print("\n[3] D2XX devices (ftd2xx):", flush=True)
    if ftd2xx_ok:
        try:
            n = ftd.createDeviceInfoList()
            print(f"    createDeviceInfoList() -> {n} device(s)", flush=True)
            for i in range(n):
                try:
                    info = ftd.getDeviceInfoDetail(i)
                    if isinstance(info, dict):
                        ser = _decode(info.get("serial", ""))
                        desc = _decode(info.get("description", ""))
                    elif isinstance(info, (list, tuple)) and len(info) >= 6:
                        ser = _decode(info[4])
                        desc = _decode(info[5])
                    else:
                        ser = desc = "?"
                    print(f"    [{i}] serial={ser!r} description={desc!r}", flush=True)
                except Exception as e:
                    print(f"    [{i}] error: {e}", flush=True)
        except Exception as e:
            print(f"    Error: {e}", flush=True)
    else:
        print("    (skipped – using pylibftdi)", flush=True)

    # 4. Open, configure, and test read timeout (ftd2xx)
    print("\n[4] Open device and test timeouts (ftd2xx):", flush=True)
    if ftd2xx_ok:
        try:
            n_dev = ftd.createDeviceInfoList()
            if n_dev == 0:
                print("    No D2XX devices found – skip open test.", flush=True)
            else:
                dev = ftd.open(0)
                print("    open(0) -> OK", flush=True)
        except Exception as e:
            print(f"    open(0) -> FAILED: {e}", flush=True)
            return 1

        if n_dev > 0:
            try:
                dev.setBaudRate(115200)
                print("    setBaudRate(115200) -> OK", flush=True)
            except Exception as e:
                print(f"    setBaudRate(115200) -> FAILED: {e}", flush=True)

            try:
                dev.setTimeouts(5000, 5000)
                print("    setTimeouts(5000, 5000) -> OK (read/write timeout 5 s)", flush=True)
            except AttributeError:
                print("    setTimeouts -> NOT FOUND (reads may block indefinitely!)", flush=True)
            except Exception as e:
                print(f"    setTimeouts(5000, 5000) -> FAILED: {e}", flush=True)

            # Test with and without RTS/CTS flow control
            try:
                rts_cts = getattr(ftd, 'FT_FLOW_RTS_CTS', 256)
                dev.setFlowControl(rts_cts, 0, 0)
                print("    setFlowControl(RTS/CTS) -> OK", flush=True)
            except (AttributeError, TypeError) as e:
                print(f"    setFlowControl(RTS/CTS) -> NOT AVAILABLE: {e}", flush=True)
            except Exception as e:
                print(f"    setFlowControl(RTS/CTS) -> FAILED: {e}", flush=True)

            try:
                dev.purge()
                print("    purge() -> OK", flush=True)
            except Exception as e:
                print(f"    purge() -> FAILED: {e}", flush=True)

            # Test read with timeout: should return within ~5 s even if no data
            print("    read(1) with 5 s timeout (no data expected) ...", flush=True)
            t0 = time.perf_counter()
            try:
                data = dev.read(1)
                elapsed = time.perf_counter() - t0
                print(f"    read(1) returned after {elapsed:.2f} s: {data!r}", flush=True)
                if elapsed > 6:
                    print("    WARNING: read() took > 5 s – driver timeout may not be set.", flush=True)
            except Exception as e:
                elapsed = time.perf_counter() - t0
                print(f"    read(1) raised after {elapsed:.2f} s: {e}", flush=True)

            # Test PING command (command 2) - write packet and read response
            print("    Testing PING command (write + read response) ...", flush=True)
            try:
                from Morelia.Devices import Pod
                ping_packet = Pod.build_pod_packet_standard(2)  # PING command (no payload)
                print(f"    PING packet: {ping_packet.hex()}", flush=True)
                # Check modem status (CTS) before write if available
                try:
                    modem_status = dev.getModemStatus()
                    cts = (modem_status & 0x10) != 0  # Bit 4 is CTS
                    print(f"    Modem status before write: CTS={'asserted' if cts else 'not asserted'}", flush=True)
                except (AttributeError, TypeError):
                    pass
                written = dev.write(ping_packet)
                print(f"    write(PING) -> OK ({written} bytes written)", flush=True)
                # Small delay to allow device to process
                time.sleep(0.01)
                # Check modem status after write
                try:
                    modem_status = dev.getModemStatus()
                    cts = (modem_status & 0x10) != 0
                    print(f"    Modem status after write: CTS={'asserted' if cts else 'not asserted'}", flush=True)
                except (AttributeError, TypeError):
                    pass
                t0 = time.perf_counter()
                response = dev.read(8)  # Read up to 8 bytes (min POD packet size) - uses timeout from setTimeouts
                elapsed = time.perf_counter() - t0
                if response:
                    print(f"    read(response) -> {response.hex()} after {elapsed:.2f} s", flush=True)
                    if len(response) >= 6 and response[0] == 0x02:  # STX
                        print("    PING response: OK (valid POD packet)", flush=True)
                    else:
                        print("    PING response: WARNING (unexpected format)", flush=True)
                else:
                    print(f"    read(response) -> None (timeout) after {elapsed:.2f} s", flush=True)
            except Exception as e:
                print(f"    PING test -> FAILED: {e}", flush=True)
                import traceback
                traceback.print_exc()

            try:
                dev.close()
                print("    close() -> OK", flush=True)
            except Exception as e:
                print(f"    close() -> FAILED: {e}", flush=True)
    else:
        print("    (skipped – using pylibftdi)", flush=True)

    # 5. Morelia D2XXPortIO quick test (optional)
    print("\n[5] Morelia D2XXPortIO (open + read timeout):", flush=True)
    try:
        from Morelia.Devices.SerialPorts import D2XXPortIO, D2XX_AVAILABLE
        if not D2XX_AVAILABLE:
            print("    D2XX_AVAILABLE is False", flush=True)
        else:
            # Use index 0 or first device serial
            port = 0
            print(f"    Opening device (port={port!r}) ...", flush=True)
            io = D2XXPortIO(port, 115200)
            t0 = time.perf_counter()
            data = io.read(1, timeout_sec=2)
            elapsed = time.perf_counter() - t0
            print(f"    D2XXPortIO.read(1, timeout_sec=2) -> {data!r} after {elapsed:.2f} s", flush=True)
            if elapsed > 2.5:
                print("    WARNING: read took longer than 2 s – check setTimeouts on device.", flush=True)

            # Test PING command using D2XXPortIO
            print("    Testing PING command (write + read response) ...", flush=True)
            try:
                from Morelia.Devices import Pod
                ping_packet = Pod.build_pod_packet_standard(2)  # PING command (no payload)
                print(f"    PING packet: {ping_packet.hex()}", flush=True)
                # Check if we can access modem status through the handle
                try:
                    modem_status = io._ftd2xx_handle.getModemStatus()
                    cts = (modem_status & 0x10) != 0
                    print(f"    Modem status before write: CTS={'asserted' if cts else 'not asserted'}", flush=True)
                except (AttributeError, TypeError):
                    pass
                io.write(ping_packet)
                print("    write(PING) -> OK", flush=True)
                # Small delay to allow device to process and respond
                time.sleep(0.01)
                # Check modem status after write
                try:
                    modem_status = io._ftd2xx_handle.getModemStatus()
                    cts = (modem_status & 0x10) != 0
                    print(f"    Modem status after write: CTS={'asserted' if cts else 'not asserted'}", flush=True)
                except (AttributeError, TypeError):
                    pass
                t0 = time.perf_counter()
                response = io.read(8, timeout_sec=5)  # Read up to 8 bytes (min POD packet size)
                elapsed = time.perf_counter() - t0
                if response:
                    print(f"    read(response) -> {response.hex()} after {elapsed:.2f} s", flush=True)
                    if len(response) >= 6 and response[0] == 0x02:  # STX
                        print("    PING response: OK (valid POD packet)", flush=True)
                    else:
                        print("    PING response: WARNING (unexpected format)", flush=True)
                else:
                    print(f"    read(response) -> None (timeout) after {elapsed:.2f} s", flush=True)
            except Exception as e:
                print(f"    PING test -> FAILED: {e}", flush=True)
                import traceback
                traceback.print_exc()

            io.close_serial_port()
            print("    close_serial_port() -> OK", flush=True)
    except Exception as e:
        print(f"    Error: {e}", flush=True)
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60, flush=True)
    print("Diagnostic complete. If [4] read() blocks > 5 s, install/set D2XX", flush=True)
    print("driver timeouts (e.g. setTimeouts). If device does not appear in [3],", flush=True)
    print("check USB connection and FTDI D2XX drivers.", flush=True)
    print("=" * 60, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

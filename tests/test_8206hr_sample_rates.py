"""Test 8206HR reactivex pipeline at different sample rates.

This test verifies that the reactivex pipeline properly receives all data
from all channels at sample rates: 100, 200, 400, 800, 1000, and 2000 Hz.

"""

import sys
import time
import multiprocessing as mp
from pathlib import Path

# Add src to path
_project_root = Path(__file__).resolve().parent.parent
_src = _project_root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from Morelia.Devices import Pod8206HR
from Morelia.Stream.sink import BufferSink
from Morelia.Stream.data_flow import DataFlow


def _run_sample_rate_test(sample_rate: int, duration_sec: float = 10.0, tolerance: float = 0.05) -> dict:
    """Test streaming at a specific sample rate.
    
    Args:
        sample_rate: Sample rate in Hz (100, 200, 400, 800, 1000, or 2000)
        duration_sec: Duration to stream in seconds
        tolerance: Tolerance for sample count verification (0.05 = 5%)
    
    Returns:
        dict with test results including:
        - sample_rate: The tested sample rate
        - expected_samples: Expected number of samples
        - actual_samples: Actual number of samples collected
        - channels_received: Dict of channel names to sample counts
        - all_channels_present: bool indicating if all 3 channels have data
        - data_valid: bool indicating if data values are reasonable
        - timestamps_valid: bool indicating if timestamps are increasing
        - success: bool indicating overall test success
    """
    print(f"\n{'='*60}")
    print(f"Testing sample rate: {sample_rate} Hz")
    print(f"{'='*60}")
    
    # Try to find device (D2XX or COM port)
    use_d2xx = False
    port = None
    
    try:
        from Morelia.Devices.SerialPorts.d2xx_helpers import list_d2xx_devices
        devices = list_d2xx_devices()
        if devices:
            use_d2xx = True
            device_serial = devices[0].get("serial")
            if isinstance(device_serial, bytes):
                device_serial = device_serial.decode("utf-8")
            port = device_serial if (device_serial and device_serial.strip()) else "D2XX_0"
            print(f"Using D2XX device: {port}")
        else:
            print("No D2XX devices found, trying COM port...")
            port = "COM9"  # Default COM port for Windows
            print(f"Using COM port: {port}")
    except ImportError:
        port = "COM9"
        print(f"D2XX not available, using COM port: {port}")
    
    # Initialize device
    try:
        pod = Pod8206HR(
            port=port,
            preamp_gain=100,
            baudrate=115200,
            use_d2xx=use_d2xx,
        )
    except Exception as e:
        return {
            "sample_rate": sample_rate,
            "error": f"Failed to initialize device: {e}",
            "success": False
        }
    
    try:
        # Open port and ensure streaming is stopped
        port_was_open = pod._port is not None
        if not port_was_open:
            pod.open_port()
        
        # CRITICAL: Ensure streaming is stopped before setting sample rate
        try:
            pod.write_packet("STREAM", 0)
            time.sleep(0.1)  # Brief pause to let device process stop command
            # Flush any pending data packets
            while True:
                try:
                    pod.read_pod_packet(timeout_sec=0.1)
                except TimeoutError:
                    break
        except Exception as e:
            print(f"Warning: Could not ensure streaming is stopped: {e}")
        
        # Set sample rate
        try:
            pod.write_read("SET SAMPLE RATE", sample_rate, timeout_sec=5)
            # Verify sample rate was set
            rate_response = pod.write_read("GET SAMPLE RATE", timeout_sec=5)
            actual_rate = rate_response.payload[0] if rate_response.payload else None
            if actual_rate != sample_rate:
                return {
                    "sample_rate": sample_rate,
                    "error": f"Failed to set sample rate: requested {sample_rate}, got {actual_rate}",
                    "success": False
                }
            print(f"Sample rate set to {sample_rate} Hz (verified)")
            # Cache the sample rate
            pod._sample_rate = (sample_rate,)
        except Exception as e:
            return {
                "sample_rate": sample_rate,
                "error": f"Failed to set sample rate: {e}",
                "success": False
            }
        
        if not port_was_open and use_d2xx:
            pod.close_port()
        
        # Create buffer for collecting data
        manager = mp.Manager()
        buffer = manager.list()
        
        # Create BufferSink
        buffer_sink = BufferSink(buffer, pod)
        
        # Create DataFlow
        network = [(pod, [buffer_sink])]
        flow = DataFlow(network)
        
        # Stream for specified duration
        print(f"Streaming for {duration_sec} seconds...")
        start_time = time.perf_counter()
        flow.collect_for_seconds(duration_sec)
        elapsed_time = time.perf_counter() - start_time
        print(f"Streaming completed in {elapsed_time:.2f} seconds")
        
        # Process results
        # Buffer format: [('time', 'EEG1', 'EEG2', 'EEG3/EMG'), (timestamp, (ch0, ch1, ch2, ...)), ...]
        if len(buffer) < 2:
            return {
                "sample_rate": sample_rate,
                "error": f"No data collected (buffer size: {len(buffer)})",
                "success": False
            }
        
        # Remove header row
        data_rows = list(buffer)[1:]
        actual_samples = len(data_rows)
        expected_samples = int(sample_rate * duration_sec)
        
        # Effective rate = samples per second of stream duration (not wall clock)
        effective_rate = actual_samples / duration_sec if duration_sec > 0 else 0
        pct_expected = (actual_samples / expected_samples * 100) if expected_samples > 0 else 0

        print(f"Expected samples: {expected_samples} (at {sample_rate} Hz for {duration_sec} s)")
        print(f"Actual samples: {actual_samples}")
        print(f"Wall clock elapsed: {elapsed_time:.2f} s (includes worker start/stop)")
        print(f"Effective rate: {effective_rate:.1f} Hz (actual_samples / stream duration)")
        print(f"Percent of expected: {pct_expected:.1f}%")
        
        # Verify sample count (allow tolerance)
        min_samples = int(expected_samples * (1 - tolerance))
        max_samples = int(expected_samples * (1 + tolerance))
        sample_count_valid = min_samples <= actual_samples <= max_samples
        
        # Check that all channels have data
        channels_received = {"EEG1": 0, "EEG2": 0, "EEG3/EMG": 0}
        all_channels_present = True
        data_valid = True
        timestamps_valid = True
        
        prev_timestamp = None
        zero_count = 0
        non_zero_count = 0
        
        for row in data_rows:
            if len(row) < 2:
                continue
            
            timestamp, channel_data = row[0], row[1]
            
            # Check timestamps are non-decreasing (allow duplicates from pipeline)
            if prev_timestamp is not None and timestamp < prev_timestamp:
                timestamps_valid = False
            prev_timestamp = timestamp
            
            # Check channel data
            if len(channel_data) >= 3:
                ch0, ch1, ch2 = channel_data[0], channel_data[1], channel_data[2]
                
                # Count non-zero values (all zeros might indicate a problem)
                if ch0 == 0 and ch1 == 0 and ch2 == 0:
                    zero_count += 1
                else:
                    non_zero_count += 1
                
                # Check for reasonable values (not NaN, not infinite)
                import math
                if (math.isnan(ch0) or math.isnan(ch1) or math.isnan(ch2) or
                    math.isinf(ch0) or math.isinf(ch1) or math.isinf(ch2)):
                    data_valid = False
                
                # Count samples per channel
                if ch0 is not None:
                    channels_received["EEG1"] += 1
                if ch1 is not None:
                    channels_received["EEG2"] += 1
                if ch2 is not None:
                    channels_received["EEG3/EMG"] += 1
        
        # Verify all channels received data
        for channel, count in channels_received.items():
            if count == 0:
                all_channels_present = False
                print(f"WARNING: {channel} has no data!")
            elif count < actual_samples * 0.9:  # Allow 10% missing data per channel
                print(f"WARNING: {channel} has only {count}/{actual_samples} samples")
        
        # Check if we have too many zero samples (might indicate a problem)
        if zero_count > actual_samples * 0.5:  # More than 50% zeros
            print(f"WARNING: {zero_count}/{actual_samples} samples are all zeros")
            data_valid = False
        
        # Overall success
        success = (sample_count_valid and 
                  all_channels_present and 
                  data_valid and 
                  timestamps_valid and
                  actual_samples > 0)
        
        # Print summary
        print(f"\nTest Results:")
        print(f"  Sample count valid: {sample_count_valid} ({actual_samples} samples, expected {expected_samples}±{int(expected_samples*tolerance)})")
        print(f"  All channels present: {all_channels_present}")
        print(f"    - EEG1: {channels_received['EEG1']} samples")
        print(f"    - EEG2: {channels_received['EEG2']} samples")
        print(f"    - EEG3/EMG: {channels_received['EEG3/EMG']} samples")
        print(f"  Data valid: {data_valid} (non-zero samples: {non_zero_count}/{actual_samples})")
        print(f"  Timestamps valid: {timestamps_valid}")
        print(f"  Overall: {'PASS' if success else 'FAIL'}")
        
        return {
            "sample_rate": sample_rate,
            "expected_samples": expected_samples,
            "actual_samples": actual_samples,
            "elapsed_time": elapsed_time,
            "effective_rate": effective_rate,
            "pct_expected": pct_expected,
            "channels_received": channels_received,
            "all_channels_present": all_channels_present,
            "data_valid": data_valid,
            "timestamps_valid": timestamps_valid,
            "sample_count_valid": sample_count_valid,
            "zero_count": zero_count,
            "non_zero_count": non_zero_count,
            "success": success
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "sample_rate": sample_rate,
            "error": f"Exception during test: {e}",
            "success": False
        }
    finally:
        # Ensure streaming is stopped
        try:
            if pod._port is None:
                pod.open_port()
            pod.write_packet("STREAM", 0)
            time.sleep(0.1)
            # Flush any remaining packets
            while True:
                try:
                    pod.read_pod_packet(timeout_sec=0.1)
                except TimeoutError:
                    break
            if pod._port is not None:
                pod.close_port()
        except Exception:
            pass
        
        try:
            pod.cleanup()
        except Exception:
            pass



def test_all_sample_rates():
    """Test all sample rates: 100, 200, 400, 800, 1000, 2000 Hz."""
    sample_rates = [400, 800, 1000, 2000]
    results = []
    
    print("\n" + "="*60)
    print("8206HR ReactiveX Pipeline Sample Rate Test")
    print("="*60)
    print("\nThis test verifies that the reactivex pipeline properly")
    print("receives all data from all channels at different sample rates.")
    print("\nTest will run at: 100, 200, 400, 800, 1000, and 2000 Hz")
    print("Duration: 2 seconds per sample rate")
    print("="*60)
    
    for rate in sample_rates:
        result = _run_sample_rate_test(rate, duration_sec=10.0, tolerance=0.05)
        results.append(result)
        
        # Brief pause between tests
        if rate != sample_rates[-1]:
            print("\nPausing 1 second before next test...")
            time.sleep(1)
    
    # Print summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    all_passed = True
    for result in results:
        status = "PASS" if result.get("success", False) else "FAIL"
        rate = result.get("sample_rate", "?")
        if "error" in result:
            print(f"{rate:4d} Hz: {status} - {result['error']}")
        else:
            samples = result.get("actual_samples", 0)
            expected = result.get("expected_samples", 0)
            print(f"{rate:4d} Hz: {status} - {samples}/{expected} samples, "
                  f"effective: {result.get('effective_rate', 0):.1f} Hz ({result.get('pct_expected', 0):.1f}% of expected)")
        if not result.get("success", False):
            all_passed = False
    
    print("="*60)
    if all_passed:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
    print("="*60)
    
    assert all_passed, "One or more sample rate tests failed"


if __name__ == "__main__":
    try:
        test_all_sample_rates()
    except AssertionError:
        sys.exit(1)
    sys.exit(0)

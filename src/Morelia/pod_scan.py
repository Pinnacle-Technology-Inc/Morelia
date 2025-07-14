import os
from Morelia.Devices.BasicPodProtocol import Pod

def detect_pod_devices():
    print("Scanning /dev...")
    devices = os.listdir('/dev')
    print("Found devices:", devices)

    usb_devices = [f'/dev/{x}' for x in devices if 'ttyUSB' in x]
    print(f"Filtered USB devices: {usb_devices}")

    pod_devices = []

    for port in usb_devices:
        pod = Pod(port)
        if pod.test_connection():
            try:
                device_type = pod.write_read('TYPE').payload[0]
                device_id = pod.write_read('ID').payload[0]
                pod_devices.append({
                    'PORT': port,
                    'TYPE': str(device_type),
                    'ID': str(device_id),
                })
                print(f"Pod Device found on {port} with type {device_type} and ID {device_id}")
            except Exception as e:
                print(f"Error communicating with device on {port}: {e}")
        else:
            print(f"Device on {port} did not respond to test_connection.")

    return pod_devices


detect_pod_devices()

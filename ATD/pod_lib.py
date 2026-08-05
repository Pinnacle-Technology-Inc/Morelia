import os
import platform
import serial.tools.list_ports

from Morelia.Devices.BasicPodProtocol import Pod

#pod device type lookup table
pod_types = {'8206HR':48, 'ATD':99, '8401HR':49}
reverse_pod_types = {48:'8206HR', 99:'ATD', 49:'8401HR'}

#returns a list of USB devices
# def usb_scan():
#     devices = os.listdir('/dev')
#     usb_devices = []
    
#     for x in devices:
#         if 'ttyUSB' in x:
#             usb_devices. append('/dev/' + x)
    
#     if devices != []:
#         return usb_devices
#     else:
#         raise Exception("No USB devices found - check connection and that the devices are loaded in VirtualBox")

def usb_scan():

    usb_devices = []

    if platform.system() == "Windows":
        for port in serial.tools.list_ports.comports():
            usb_devices.append(port.device)

    else:
        devices = os.listdir('/dev')
        for x in devices:
            if 'ttyUSB' in x or 'ttyACM' in x:
                usb_devices.append('/dev/' + x)

    if usb_devices:
        return usb_devices
    else:
        raise Exception("No USB devices found - check connection")


#checks if USB devices are Pod devices, and if so returns a list of Pod devices
def pod_scan(usb_devices):

    pod_devices = []
    
    for x in usb_devices:
        try: 
            pod_test = Pod(x)
            if (pod_test.test_connection()):
                device_type = pod_test.write_read('TYPE').payload[0]
                try:
                    device_id = pod_test.write_read('ID').payload[0]
                except:
                    print("Current firmware does not support ID - firmware update required")
                    device_id = None
                firmware_ver = pod_test.write_read('FIRMWARE VERSION').payload
                pod_devices.append({'PORT':x, 'TYPE':device_type, 'ID':device_id, 'FW': firmware_ver})
        except:
            print ("Port IO Error: Try removing/replacing devices")
    
    if pod_devices != []:
        return pod_devices
    else:
        raise Exception('No Pod devices found.  Check connections') 

#
# Intel hex based Python bootloader for Pod devices
# Will attempt to bootload any USB device in /dev/TTYUSBX
# Will lock on failure, so make sure there's no other devices and they're all in bootload mode

from boot_lib import *
from pod_lib import reverse_pod_types
import os

file_path = os.getenv('HOME') + '/Desktop/firmware/'

file_list = hex_scan(file_path)
print(f"{len(file_list)} hex files found")
for x in file_list:
    print(f"{reverse_pod_types[x]} - ver {file_list[x][1][0]}.{file_list[x][1][1]}.{file_list[x][1][2]}")

usb_list = usb_scan()
print(f"{len(usb_scan())} USB devices found")
for x in usb_list:
    print(x)

pod_list = pod_scan(usb_list)
print(f"{len(pod_list)} Pod devices found")
for x in pod_list:
    print(f"{x['PORT']} - {reverse_pod_types[x['TYPE']]} - ID: {x['ID']} - ver {x['FW'][0]}.{x['FW'][1]}.{x['FW'][2]}")

for x in pod_list:
    dev_fw = x['FW']
    dev_type = x['TYPE']
    print (f"Checking for valid firmware for device type {reverse_pod_types[x['TYPE']]}")
    if x['TYPE'] in file_list:
        print("Firmware found")
        print(f"Checking FW revision for {x['PORT']}")
        if x['FW'] < file_list[x['TYPE']][1]:
            print (f"Current FW: {x['FW']} - updating to {file_list[x['TYPE']][1]}")
            #enable the bootload mode on the device
            #load the hex file into memory
            update_file = read_intel_hex(file_list[x['TYPE']][0])
            #Check we have a valid update file
            if validate_intel_hex(update_file):
                pod_enable_bootload(x['PORT'])
                lines_sent = pod_bootload(x['PORT'], update_file)
                if lines_sent == len(update_file):
                    print(f"Bootload completed successfully - {lines_sent} lines sent")
                else:
                    print(f"Bootload failed - {lines_sent} lines sent")
            else:
                print(f"Validation check failed - {file_list[x['TYPE']][0]} invalid or corrupted")
        else:
            print ("Firmware is up to date")
    else:
        print(f"Valid firmware for device type {x['TYPE']} not found")


#for x in usb_list:
#    print ("Attempting to bootload device found at " + x)
#    lines_sent = bootload(x, hex)
#    if lines_sent == len(hex):
#        print (str(lines_sent) + ' lines sent')
#        print ('Bootloading complete')

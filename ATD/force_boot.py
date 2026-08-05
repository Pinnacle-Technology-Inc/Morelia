#
# Intel hex based Python bootloader for Pod devices
# Will attempt to bootload any USB device in /dev/TTYUSBX
# Will lock on failure, so make sure there's no other devices and they're all in bootload mode

from boot_lib import *
import os

hpf_types = ['SL', 'SE', 'SE3']

file_path = os.getenv('HOME') + '/Desktop/firmware/'

file_list = hex_scan(file_path)
print(f"{len(file_list)} hex files found")
for x in file_list:
    print(f"{reverse_pod_types[x]} - ver {file_list[x][1][0]}.{file_list[x][1][1]}.{file_list[x][1][2]}")

usb_list = usb_scan()
print(f"{len(usb_scan())} USB devices found")
for x in usb_list:
    print(x)

print("-------------------------")
print("WARNING: this program has no protection against loading incorrect firmware on a device")
print("Incorrect firmware may cause damage to the device or make it inoperable")
print("Ensure the device type matches the firmware being loaded before continuing")
print("-------------------------")
print('')

if file_list == {}:
    print ("No firmware files found - exiting")
    exit()

if usb_list == []:
    print ("No USB devices found - exiting")
    exit()


print('Select device type from available firmware files:')
select_list = []
for x in file_list:
    select_list.append(reverse_pod_types[x])
for x in range(len(select_list)):
    print (f"{x}: {select_list[x]}")

device_type = ''
while device_type == '':
    try:
        choice = int(input())
        if choice in range(len(select_list)):
            device_type = pod_types[select_list[choice]]
        else:
            print("Please select a value from the list")
    except:
        print("Please select a value from the list")

print ('Select USB Device to load:')

for x in range(len(usb_list)):
    print (f"{x}: {usb_list[x]}")

device = ''
while device == '':
    try:
        choice = int(input())
        if choice in range(len(usb_list)):
            device = usb_list[x]
        else:
            print("Please select a value from the list")
    except:
        print("Please select a value from the list")
        
print(f"Device {device} will be loaded with file {file_list[device_type][0]} - do you want to continue? (Y/n)")
    
choice = input()

if choice != 'Y':
    print("Exiting")
    exit()
else:
    print("Ensure device is in bootload mode - hold BOOT/B0 button on PCB and press RESET button. Press ENTER to continue.")
    input()
    print("If device is not in bootload mode or bootloader is damaged, this program may hang")
    print("Press CTRL+Z to exit if this happens.  Press ENTER to continue")
    input()
    print ("Attempting to bootload device found at " + device, flush=True)
    
    update_file = read_intel_hex(file_list[device_type][0])
    if validate_intel_hex(update_file):
        print ("Hex file validated - proceeding with bootload", flush=True)
        lines_sent = pod_bootload(device, update_file)

        if lines_sent == len(update_file):
            print (str(lines_sent) + ' lines sent')
            print ('Bootloading complete')
        else:
            print (f'Bootload error - {lines_sent} lines sent')
    else:
        print ("Hex file validation failed - exiting")


#for x in usb_list:
#    print ("Attempting to bootload device found at " + x)
#    lines_sent = bootload(x, hex)
#    if lines_sent == len(hex):
#        print (str(lines_sent) + ' lines sent')
#        print ('Bootloading complete')

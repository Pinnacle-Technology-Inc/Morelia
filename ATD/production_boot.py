#
# Intel hex based Python bootloader for Pod devices
# Will attempt to bootload any USB device in /dev/TTYUSBX
# Will lock on failure, so make sure there's no other devices and they're all in bootload mode

from boot_lib import *
from Morelia.Devices import Pod8206HR
import os, time

hpf_types = {0:'SL', 1:'SE', 2:'SE3'}

file_path = os.getenv('HOME') + '/Desktop/firmware/'

file_list = hex_scan(file_path)
print(f"{len(file_list)} hex files found")
for x in file_list:
    print(f"{reverse_pod_types[x]} - ver {file_list[x][1][0]}.{file_list[x][1][1]}.{file_list[x][1][2]}")

usb_list = usb_scan()
usb_list.sort() # for serialization, it's nice to have the list in the order the devices are connected. 
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

print('Enter initial serial number.  Serial number will be incremented by 1 for each device.  This does not affect USB serial ID.  Press X to skip')

#use sequential serial programming
serial_number = None
while serial_number == None:
    user_input = input()
    if user_input == 'X':
        serial_number = 'X'
    else:
        try:
            user_input = abs(int(user_input))
            if user_input >= 65535:
                print("Values must be between 0-65535")
            else:
                serial_number = user_input
        except:
            print("Integer values only from 0-65535")

#set HPF types if they're 8206s
hpf_type = None
if device_type == pod_types['8206HR']:
    
    print ("Input HPF config - 0 = SL, 1 = SE, 2 = SE3 - or press X to cancel")

    while hpf_type == None:
        user_input = input()
        if user_input == 'X':
            hpf_type = 'X'
        else:
            try:
                user_input = abs(int(user_input))
                if user_input >= 3:
                    print("Values must be 0, 1, or 2")
                else:
                    hpf_type = user_input
            except:
                print("Integer values only from 0-2")

# just clear the HPF type if we bailed so it's easier to handle later


print(f"All pod devices will be loaded with file {file_list[device_type][0]}")
if serial_number != 'X':
    print(f'Devices will be serialized starting at {serial_number}')
if hpf_type != '':
    print(f'8206 devices will be set to {hpf_types[hpf_type]}')
print('Ensure all devices are in bootload mode before continuing')
print ("Do you want to continue? (Y/n)")
    
choice = input()

if choice != 'Y':
    print("Exiting")
    exit()

for x in usb_list:  
    #do the bootload first
    update_file = read_intel_hex(file_list[device_type][0])
    
    if validate_intel_hex(update_file):
        print ("Attempting to bootload device found at " + x, flush=True)
        print ("Hex file validated - proceeding with bootload", flush=True)
        
        lines_sent = pod_bootload(x, update_file)

        if lines_sent == len(update_file):
            print (str(lines_sent) + ' lines sent')
            print ('Bootloading complete')
            time.sleep(1)   #wait for a second after bootloading
        else:
            print (f'Bootload error - {lines_sent} lines sent')
            exit() # if the bootload fails, bail out            
    else:
        print ("Hex file validation failed - exiting")
        exit() # if the bootload fails, bail out entirely
        
    #do the serial number set second
    if serial_number != 'X':
        print(f'Attempting to set serial number to {serial_number}')
        pod = Pod8206HR(x, 100)
        pod.write_read('SET ID', (serial_number,))
        readback = pod.write_read('ID').payload[0]
        if readback == serial_number:
            print(f'Device ID successfully set to {serial_number}') 
            pod.write_read('SAVE SETTINGS', (0,))
            serial_number += 1
        else:
            print(f'Device ID set failure - {serial_number} != {readback}')
    
    if hpf_type in hpf_types:
        print(f'Attempting to set device filter type to {hpf_types[hpf_type]}')
        pod = Pod8206HR(x, 100)
        pod.write_read('SET FILTER CONFIG', (hpf_type,))
        readback = pod.write_read('GET FILTER CONFIG').payload[0]
        if readback == hpf_type:
            print(f'High Pass Config successfully set to {hpf_types[hpf_type]}')
            pod.write_read('SAVE SETTINGS', (0,))
        else:
            print(f'High Pass Config set failure - {hpf_type} != {readback}')
        

#for x in usb_list:
#    print ("Attempting to bootload device found at " + x)
#    lines_sent = bootload(x, hex)
#    if lines_sent == len(hex):
#        print (str(lines_sent) + ' lines sent')
#        print ('Bootloading complete')

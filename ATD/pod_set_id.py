from pod_lib import *
from Morelia.Devices import Pod8206HR

hpf_types = ['SL', 'SE', 'SE3']

usb_list = usb_scan()
print(f"{len(usb_scan())} USB devices found")
print (usb_list)
pod_list = pod_scan(usb_list)
print(f"{len(pod_list)} Pod devices found")

if pod_list == []:
    raise Exception ("No pod devices found")
    
print ("Which device do you want to set? or X to exit")
for x in range (len(pod_list)):
    if pod_list[x]['ID'] != None: 
        print (f"{x}: {pod_list[x]['PORT']} - {reverse_pod_types[pod_list[x]['TYPE']]} - ID: {pod_list[x]['ID']} - FW: {pod_list[x]['FW']}")
    
selection = ''

while selection == '':
    user_input = input()
    
    if user_input == 'x' or user_input == 'X':
        exit()
    
    try:
        user_input = abs(int(user_input))
        if user_input >= len(pod_list):
            print("Selection out of range")
        else:
            selection = user_input
    except:
        print("Must select from list - or X to exit")

# if this is an 8206HR connect as an 8206HR, not a generic pod, so we can set the HPF config
if pod_list[selection]['TYPE'] == pod_types['8206HR']:
    pod = Pod8206HR(pod_list[selection]['PORT'], 100)
    hpf = pod.write_read('GET FILTER CONFIG').payload[0]
    pod_list[selection]['HPF'] = hpf
else:
    pod = Pod(pod_list[selection]['PORT'])

current_id = pod.write_read('ID').payload[0]
print (f"Current device ID - {current_id}")

print ("Input new ID - 0-65535")

new_id = ''
while new_id == '':
    user_input = input()
    try:
        user_input = abs(int(user_input))
        if user_input >= 65535:
            print("Values must be between 0-65535")
        else:
            new_id = user_input
    except:
        print("Integer values only from 0-65535")

#if this is an 8206HR also set the HPF type
if pod_list[selection]['TYPE'] == pod_types['8206HR']:
    hpf = pod.write_read('GET FILTER CONFIG').payload[0]
    if hpf == 255:
        print("HPF not set")
    else:
        print (f"HPF config = {hpf_types[hpf]}")
    
    print ("Input HPF config - 0 = SL, 1 = SE, 2 = SE3 - or press X to cancel")
    
    new_hpf = None
    
    while new_hpf == None:
        user_input = input()
        try:
            user_input = abs(int(user_input))
            
            if user_input == 'x' or user_input == 'X':
                break
            
            if user_input >= 3:
                print("Values must be 0, 1, or 2")
            else:
                new_hpf = user_input
        except:
            if user_input != 'x' and user_input != 'X':
                print("Integer values only from 0-2")
            else:
                break
    
    if new_hpf != None:
        pod.write_read('SET FILTER CONFIG', (new_hpf,))
        print(f"HPF set to {hpf_types[new_hpf]}") 

pod.write_read('SET ID', (new_id,))
pod.write_read('SAVE SETTINGS', (0,))

pod_id = pod.write_read('ID').payload[0]
print (f"ID set to {pod_id}")

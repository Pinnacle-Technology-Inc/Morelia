from serial import Serial
from pod_lib import *

POD_ACK = bytes('\x0200003F\x03', 'utf-8')
POD_NACK = bytes('\x0200013E\x03', 'utf-8')

# reads in the file and returns a list with each entry one line from the file
def read_intel_hex(filename):
    file = open(filename)
    hex_file = []
    line = 'EMPTY'

    while line != '':
        line = file.readline()
        if (line != ''):
            if (line[0] == ':'):
                hex_file.append(line)
    file.close()
    return (hex_file)

# for now just check for leading ':' on each line
# in the future this should probably actually parse the file and validate checksums on each line or something
def validate_intel_hex(file):
    for x in file:
        if x[0] != ':':
            return False
    return True

def pod_enable_bootload(port):
    pod = Pod(port)
    pod.write_read('BOOT')

# Writes the hex file to the device
def pod_bootload(port, file):
    device = Serial(port)
    device.close()
    device.open()

    total_lines = 0
    bootload_started = False

    for x in file:
        line = bytes(x, 'utf-8')
        #print ("sending line " +str(total_lines))
        device.write(line)
        reply = device.read(len(POD_ACK))
        
        if (reply == POD_ACK) and (bootload_started == False):
            print ('Pod bootloader detected, bootload started')
            bootload_started = True

        total_lines += 1
        print('*', end='', flush=True)
        if reply != POD_ACK: 
            print ("NACK received, exiting")
            break
            
    device.close()
    return total_lines

#Scans for .hex files and parses them for device type and version info
#Assumes that files are in the format DEVICETYPE-V.E.R.hex
#Returns a dictionary that only contains the most recent firmware version for each device type
def hex_scan(path):
    file_list = os.listdir(path)
    hex_list = []
    hex_dict = {}

    for x in file_list:
        if '.hex' in x:
            hex_list.append(x)
      
    for x in hex_list:
        file_name = x 
        dev = x.split('-')
        # only keep going if the type is known
        if dev[0] in pod_types:
            dev_type = pod_types[dev[0]] # convert the device type string to its numeric value

            #turn the version into a tuple, so that it can be compared more easily with pod payloads
            ver = dev[1].split('.hex')[0].split('.')
            ver = tuple([int(n) for n in ver])
            data = (file_name, ver)
            
            # We now have the device type in dev_type, version in ver, and filename in x
            # if the file doesn't exist yet in the dictionary, add it
            if dev_type not in hex_dict:
                hex_dict.update({dev_type:data})
            # but if it is in the dictionary, see if this record is a newer version    
            # Note that at least in Ubuntu, this never happens because the os.listdir is already sorted
            else: 
                if hex_dict[dev_type][1] < ver:
                    hex_dict.update({dev_type:data})
    
    #prepend the path back onto the filename
    for x in hex_dict:
        data = (path + hex_dict[x][0], hex_dict[x][1])
        hex_dict[x] = data
        
    return hex_dict


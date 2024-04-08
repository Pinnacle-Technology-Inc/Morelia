"""Runs all commands for a 8274D POD device.
"""

# add directory path to code 
import Path 
import time
Path.AddAPIpath()

# local imports
import  HelperFunctions as hf
from PodApi.Packets import Packet
from PodApi.Devices import Pod, Pod8274D

# authorship
__author__      = "Sree Kondi"
__maintainer__  = "Sree Kondi"
__credits__     = ["Sree Kondi","Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

def Read_8274D(pod: Pod, cmd) : 
    """Reads and prints a packet from a POD device.

    Args:
        pod (POD_Basics): 8274D Pod device to read/write. 
    """
    read: Packet = pod.ReadPODpacket()
    data: dict = read.TranslateAll()
    print('Read1:\t', data)
    if (cmd == 'LOCAL SCAN' or cmd == 'CONNECT BY ADDRESS'):
        read: Packet = pod.ReadPODpacket()
        data: dict = read.TranslateAll()
        print('Read2:\t', data)
    if (cmd.startswith('GET')|cmd.startswith('SET')) and cmd != 'SET BAUD RATE' :
        while True:
            read: Packet = pod.ReadPODpacket()
            data: dict = read.TranslateAll()
            print('Read:\t', data)
            if data.get('Command Number') == 211:
                break  # Exit the loop when Command Number is 211
    if (cmd == 'CHANNEL SCAN'):
            read: Packet = pod.ReadPODpacket()
            data: dict = read.TranslateAll()
            print('Read:\t', data)
    if (cmd == 'STREAM'):
            read: Packet = pod.ReadPODpacket()
            data: dict = read.TranslateAll()
            print('StreamRead:\t', data)
            read: Packet = pod.ReadPODpacket()
            data: dict = read.TranslateAll()
            print('StreamRead:\t', data)
     

def RunCommand_8274D(pod: Pod, cmd: str | int, payload: int | bytes | tuple[int | bytes] = None) :
    """Writes and reads a packet from a POD device and prints the results.

    Args:
        pod (POD_Basics): POD device. 
        cmd (str | int): Command name or number.
        payload (int | bytes | tuple[int  |  bytes], optional): Optional payload for the \
            command. Defaults to None.
    """
    hf.Write(pod,cmd,payload)
    Read_8274D(pod,cmd )


# create instance of an 8480-SC POD device

port: str = Pod8274D.ChoosePort()
pod = Pod8274D(port)


print('~~ BASICS ~~')

RunCommand_8274D(pod, 'PING') # Used to verify device is present and communicating
RunCommand_8274D(pod, 'TYPE') # Returns the device type value.  This is a unique value for each device.  For the 8041-HR it is 0x31
RunCommand_8274D(pod, 'ID') # Returns the device ID value 
RunCommand_8274D(pod, 'FIRMWARE VERSION') # Returns the device firmware version as 3 values.  So 1.0.10 would come back as 0x31, 0x30, 0x00, 0x41

print('~~ LOCAL SCAN ~~')
RunCommand_8274D(pod, 'LOCAL SCAN', (1))
print("Waiting 5 sec...")
time.sleep(5) 

print('~~ CONNECT BY ADDRESS ~~')
RunCommand_8274D(pod, 'CONNECT BY ADDRESS', (0, 13, 111, 254, 61, 150)) 
print("Waiting 5 sec...")
time.sleep(5) # added a delay here because pod device is continuing to read for 'CONNECT BY ADDRESS' for the next commands.

print('~~ LOCAL CONNECTION STATUS ~~')
RunCommand_8274D(pod, 'LOCAL CONNECTION STATUS', ()) 

print('~~ SET BAUD RATE ~~')
RunCommand_8274D(pod, 'SET BAUD RATE', (2)) 

print('~~ CHANNEL SCAN ~~')
RunCommand_8274D(pod, 'CHANNEL SCAN', (1)) 

print('~~ SET SAMPLE RATE ~~')
RunCommand_8274D(pod, 'SET SAMPLE RATE', (2)) 

print('~~ GET SAMPLE RATE ~~')
RunCommand_8274D(pod, 'GET SAMPLE RATE', ()) 

print('~~ SET PERIOD ~~')
RunCommand_8274D(pod, 'SET PERIOD', (3)) 

print('~~ GET PERIOD ~~')
RunCommand_8274D(pod, 'GET PERIOD', ()) 

print('~~ GET FW VERSION ~~')
RunCommand_8274D(pod, 'GET FW VERSION', ()) 

print('~~ GET HW REV ~~')
RunCommand_8274D(pod, 'GET HW REV', ()) 

print('~~ GET SERIAL NUMBER ~~')
RunCommand_8274D(pod, 'GET SERIAL NUMBER', ()) 

print('~~ GET MODEL NUMBER ~~')
RunCommand_8274D(pod, 'GET MODEL NUMBER', ()) 

print('~~ GET NAME ~~')
RunCommand_8274D(pod, 'GET NAME', ()) 

print('~~ STREAM ~~')
RunCommand_8274D(pod, 'STREAM', (1,)) 

print('~~ DISCONNECT ~~')
RunCommand_8274D(pod, 'DISCONNECT ALL', (1,)) 


# NOTE: didn't add waveform, stimulus, GET HW INFO, SERVICE DISCOVERY because they are 
# not properly implemented. asked seth about waveform and stiumuls
# and he said not to worry about those commands.
# didn't specifically add a 'COMMAND REPLY' command because, for example, 
# GET SERIAL NUMBER returns the GET SERIAL NUMBER REPLY.


# NOTE TK -- 
# This Python script is supposed to demonstrate every single command 
# available to the device, not just  what is needed for streaming. 
# Implement as many of the following as you can:

# 101	DEVICE LIST INFO
# 102	LOCAL CONNECTION INFO
# 103	LOCAL CONNECTION STATUS
# 104	DISCONNECT ALL
# 105	SET BAUD RATE
# 131	GET PERIOD
# 132	GET PERIOD REPLY
# 133	SET PERIOD
# 200	CONNECT
# 201	CONNECT REPLY
# 202	DISCONNECT
# 203	DISCONNECT REPLY
# 204	GET SERIAL NUMBER
# 205	GET SERIAL NUMBER REPLY
# 206	GET MODEL NUMBER
# 207	GET MODEL NUMBER REPLY
# 208	GET SAMPLE RATE
# 209	GET SAMPLE RATE REPLY
# 210	SET SAMPLE RATE
# 211	PROCEDURE COMPLETE
# 212	GET RSSI
# 213	GET RSSI REPLY
# 214	GET FW VERSION
# 215	GET FW VERSION REPLY
# 220	GET NAME
# 221	GET NAME REPLY

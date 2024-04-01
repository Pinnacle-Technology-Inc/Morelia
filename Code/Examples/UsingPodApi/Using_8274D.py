"""Runs all commands for a 8274D POD device.
"""

# NOTE TK -- 
# This Python script is supposed to demonstrate every single command 
# available to the device, not just  what is needed for streaming. 
# Implement as many of the following as you can:
# 2	PING
# 7	BOOT
# 8	TYPE
# 9	ID
# 12	FIRMWARE VERSION
# 100	LOCAL SCAN
# 101	DEVICE LIST INFO
# 102	LOCAL CONNECTION INFO
# 103	LOCAL CONNECTION STATUS
# 104	DISCONNECT ALL
# 105	SET BAUD RATE
# 106	CHANNEL SCAN
# 128	GET WAVEFORM
# 129	GET WAVEFORM REPLY
# 130	SET WAVEFORM
# 131	GET PERIOD
# 132	GET PERIOD REPLY
# 133	SET PERIOD
# 134	GET STIMULUS
# 135	GET STIMULUS REPLY
# 136	SET STIMULUS
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
# 216	GET HW INFO
# 217	GET HW INFO REPLY
# 218	GET HW REV
# 219	GET HW REV REPLY
# 220	GET NAME
# 221	GET NAME REPLY
# 222	CONNECT BY ADDRESS
# 223	SERVICE DISCOVERY

# add directory path to code 
import Path 
Path.AddAPIpath()

# local imports
import  HelperFunctions as hf
from    PodApi.Devices  import Pod8274D

# authorship
__author__      = "Sree Kondi"
__maintainer__  = "Sree Kondi"
__credits__     = ["Sree Kondi","Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

# create instance of an 8480-SC POD device

port: str = Pod8274D.ChoosePort()
pod = Pod8274D(port)


print('~~ BASICS ~~')

hf.RunCommand_8274D(pod, 'PING') # Used to verify device is present and communicating
hf.RunCommand_8274D(pod, 'TYPE') # Returns the device type value.  This is a unique value for each device.  For the 8041-HR it is 0x31
hf.RunCommand_8274D(pod, 'ID') # Returns the device ID value 
hf.RunCommand_8274D(pod, 'FIRMWARE VERSION') # Returns the device firmware version as 3 values.  So 1.0.10 would come back as 0x31, 0x30, 0x00, 0x41

hf.RunCommand_8274D(pod, 'LOCAL SCAN', (1))

print('~~ CONNECT BY ADDRESS ~~')
hf.RunCommand_8274D(pod, 'CONNECT BY ADDRESS', (0, 13, 111, 254, 61, 150)) 




print('~~ GET SAMPLE RATE ~~')
hf.RunCommand_8274D(pod, 'GET SAMPLE RATE', ()) 

print('~~ GET PERIOD ~~')
hf.RunCommand_8274D(pod, 'GET SAMPLE RATE', ())

print('~~ GET PERIOD ~~')
hf.RunCommand_8274D(pod, 'GET SAMPLE RATE', ())

print('~~ GET NAME ~~')
hf.RunCommand_8274D(pod, 'GET NAME', ()) 

print('~~ STREAM ~~')
hf.RunCommand_8274D(pod, 'STREAM', (1,)) 
# hf.RunCommand(pod, 'STREAM', (0,)) 



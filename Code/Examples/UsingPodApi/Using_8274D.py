"""Runs all commands for a 8274D POD device.
"""

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

# print('~~ BASICS ~~')
# hf.RunCommand(pod, 'PING') # Used to verify device is present and communicating
# hf.RunCommand(pod, 'TYPE') # Returns the device type value.  This is a unique value for each device.  For the 8480SC it is 0x32
# hf.RunCommand(pod, 'FIRMWARE VERSION') # Returns the device firmware version as 3 values.  So 1.0.10 would come back as 0x31, 0x30, 0x00, 0x41
# print('\n')

# print('~~ LOCAL SCAN ~~')
# hf.RunCommand(pod, 'LOCAL SCAN', (1,))



# print('~~ device list ~~')
# hf.RunCommand(pod, 'DEVICE LIST INFO', (0))

# print('\n')


print('~~ CONNECT BY ADDRESS ~~')
hf.RunCommand(pod, 'CONNECT BY ADDRESS', (0, 13, 111, 254, 61, 150)) 

print('~~ STREAM ~~')
hf.RunCommand(pod, 'STREAM', (1,)) 
hf.RunCommand(pod, 'STREAM', (0,)) 

# print('~~ SET SAMPLE RATE ~~')
# hf.RunCommand(pod, 'SET SAMPLE RATE', (2)) 

# print('~~ GET SAMPLE RATE ~~')
# hf.RunCommand(pod, 'GET SAMPLE RATE', ()) 

# print('~~ SET PERIOD ~~')
# hf.RunCommand(pod, 'SET PERIOD', (3)) 

# print('~~ GET PERIOD ~~')
# hf.RunCommand(pod, 'GET PERIOD', ()) 


# print('~~ SET WAVEFORM ~~')
# hf.RunCommand(pod, 'SET WAVEFORM', ()) 

# print('~~ GET WAVEFORM ~~')
# hf.RunCommand(pod, 'GET WAVEFORM', ()) 

# print('~~ CHANNEL ~~')
# hf.RunCommand(pod, 'CHANNEL SCAN', (1)) 


print('~~DISCONNECT ~~')
hf.RunCommand(pod, 'DISCONNECT ALL', ()) 


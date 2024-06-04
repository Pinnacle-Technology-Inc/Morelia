"""Runs all commands for an 8206-HR POD device.
"""

# add directory path to code 
import Path
Path.AddAPIpath()

# local imports
import  HelperFunctions as hf
from    Morelia.Devices  import Pod8206HR

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

# create instance of 8206-HR POD device

port: str = Pod8206HR.ChoosePort()
preampGain: int = 10 # can be 10 or 100
pod = Pod8206HR(port, preampGain)

# write each command:

print('~~ BASICS ~~')
hf.RunCommand(pod, 'PING') # Used to verify device is present and communicating
hf.RunCommand(pod, 'TYPE') # Returns the device type value.  This is a unique value for each device.  For the 8206HR it is 0x30
hf.RunCommand(pod, 'FIRMWARE VERSION') # Returns the device firmware version as 3 values.  So 1.0.10 would come back as 0x31, 0x30, 0x00, 0x41

print('~~ SAMPLE RATE ~~')
sampleRate: int = 1000
hf.RunCommand(pod, 'SET SAMPLE RATE', sampleRate) # Sets the sample rate of the system, in Hz. Valid values are 100 - 2000 Hz currently.
hf.RunCommand(pod, 'GET SAMPLE RATE') # Gets the current sample rate of the system, in Hz.

print('~~ LOWPASS ~~')
channel: int = 0
lowPass: int = 40
hf.RunCommand(pod, 'SET LOWPASS', (channel,lowPass)) # Sets the lowpass filter for the desired channel (0 = EEG1, 1 = EEG2, 2 = EEG3/EMG) to the desired value (11 - 500) in Hz.
hf.RunCommand(pod, 'GET LOWPASS', channel) # Gets the current sample rate of the system, in Hz.

print('~~ TTL ~~')
ttl: list[int] = [0,1,0,1]
hf.RunCommand(pod, 'SET TTL OUT', (0, ttl[0])) # Sets the selected TTL pin (0,1,2,3) to an output and sets the value (0-1).
hf.RunCommand(pod, 'SET TTL OUT', (1, ttl[1])) # "
hf.RunCommand(pod, 'SET TTL OUT', (2, ttl[2])) # "
hf.RunCommand(pod, 'SET TTL OUT', (3, ttl[3])) # "
hf.RunCommand(pod, 'GET TTL PORT') # Gets the value of the entire TTL port as a byte. Does not modify pin direction.

print('~~ FILTER CONFIG ~~')
hf.RunCommand(pod, 'GET FILTER CONFIG') # Gets the hardware filter configuration. 0=SL, 1=SE (Both 40/40/100Hz lowpass), 2 = SE3 (40/40/40Hz lowpas).

print('~~ STREAM ~~')
hf.RunCommand(pod, 'STREAM', 1) # Command to change streaming state.  0 = OFF, 1 = ON.  Reply returns the argument sent.
hf.Write(     pod, 'STREAM', 0) # "
streaming: bool = True
while(streaming): 
    try:    hf.Read(pod)
    except: streaming = False
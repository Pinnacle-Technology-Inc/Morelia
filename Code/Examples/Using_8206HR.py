import sys, os
sys.path.insert(0, os.path.join( os.path.abspath('.'), 'Code', 'API_Modules') )

# local imports
from SerialCommunication    import COM_io
from PodDevice_8206HR       import POD_8206HR

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

# ===============================================================

def ChoosePort() -> str : 
    # get ports
    portList = COM_io.GetCOMportsList()
    print('Available COM Ports: '+', '.join(portList))
    # request port from user
    choice = input('Select port: COM')
    # search for port in list
    for port in portList:
        if port.startswith('COM'+choice):
            return(port)
    print('[!] COM'+choice+' does not exist. Try again.')
    return(ChoosePort())

def Write(pod: POD_8206HR, cmd: str | int, payload: int | bytes | tuple[int | bytes] = None) : 
    write = pod.WritePacket(cmd, payload)
    write = pod.TranslatePODpacket(write)
    print('Write:\t', write)

def Read(pod: POD_8206HR) : 
    read = pod.ReadPODpacket()
    read = pod.TranslatePODpacket(read)
    print('Read:\t', read)

def RunCommand(pod: POD_8206HR, cmd: str | int, payload: int | bytes | tuple[int | bytes] = None) :
   Write(pod,cmd,payload)
   Read(pod)

# ===============================================================

# create instance of 8206-HR POD device

port: str = ChoosePort()
preampGain: int = 10 # can be 10 or 100
pod = POD_8206HR(port, preampGain)

# write each command:

print('~~ BASICS ~~')
RunCommand(pod, 'PING') # Used to verify device is present and communicating
RunCommand(pod, 'TYPE') # Returns the device type value.  This is a unique value for each device.  For the 8206HR it is 0x30
RunCommand(pod, 'FIRMWARE VERSION') # Returns the device firmware version as 3 values.  So 1.0.10 would come back as 0x31, 0x30, 0x00, 0x41

print('~~ SAMPLE RATE ~~')
sampleRate: int = 1000
RunCommand(pod, 'SET SAMPLE RATE', sampleRate) # Sets the sample rate of the system, in Hz. Valid values are 100 - 2000 Hz currently.
RunCommand(pod, 'GET SAMPLE RATE') # Gets the current sample rate of the system, in Hz.

print('~~ LOWPASS ~~')
channel: int = 0
lowPass: int = 40
RunCommand(pod, 'SET LOWPASS', (channel,lowPass)) # Sets the lowpass filter for the desired channel (0 = EEG1, 1 = EEG2, 2 = EEG3/EMG) to the desired value (11 - 500) in Hz.
RunCommand(pod, 'GET LOWPASS', channel) # Gets the current sample rate of the system, in Hz.

print('~~ TTL ~~')
ttl: list[int] = [0,1,0,1]
RunCommand(pod, 'SET TTL OUT', (0, ttl[0])) # Sets the selected TTL pin (0,1,2,3) to an output and sets the value (0-1).
RunCommand(pod, 'SET TTL OUT', (1, ttl[1])) # "
RunCommand(pod, 'SET TTL OUT', (2, ttl[2])) # "
RunCommand(pod, 'SET TTL OUT', (3, ttl[3])) # "
RunCommand(pod, 'GET TTL PORT') # Gets the value of the entire TTL port as a byte. Does not modify pin direction.

print('~~ FILTER CONFIG ~~')
RunCommand(pod, 'GET FILTER CONFIG') # Gets the hardware filter configuration. 0=SL, 1=SE (Both 40/40/100Hz lowpass), 2 = SE3 (40/40/40Hz lowpas).

print('~~ STREAM ~~')
RunCommand(pod, 'STREAM', 1) # Command to change streaming state.  0 = OFF, 1 = ON.  Reply returns the argument sent.
Write(     pod, 'STREAM', 0) # "
streaming: bool = True
while(streaming): 
    try:
        Read(pod)
    except:
        streaming = False
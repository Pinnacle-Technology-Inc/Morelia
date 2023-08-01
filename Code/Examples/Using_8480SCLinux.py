# add directory path to code 
import Path 
Path.AddAPItoPath()

# local imports
from SerialCommunication import COM_io
from PodDevice_8480SC import POD_8480SC

# authorship
__author__      = "Sree Kondi"
__maintainer__  = "Sree Kondi"
__credits__     = ["Sree Kondi","Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

# ===============================================================

def ChoosePort() -> str : 
    # get ports
    portList = COM_io.GetCOMportsList()
    print('Available Serial Ports: '+', '.join(portList))
    # request port from user
    choice = input('Select port: /dev/tty')
    #search for port in list
    for port in portList:
        if port.startswith('/dev/tty'+choice):
            name = port.split(' ')[0]
            return(name)
    print('[!] tty'+choice+' does not exist. Try again.')
    return(ChoosePort())


def Write(pod: POD_8480SC, cmd: str | int, payload: int | bytes | tuple[int | bytes] = None) : 
    write = pod.WritePacket(cmd, payload)
    write = pod.TranslatePODpacket(write)
    print('Write:\t', write)

def Read(pod: POD_8480SC) : 
    read = pod.ReadPODpacket()
    read = pod.TranslatePODpacket(read)
    print('Read:\t', read)

def RunCommand(pod: POD_8480SC, cmd: str | int, payload: int | bytes | tuple[int | bytes] = None) :
   Write(pod,cmd,payload)
   Read(pod)

# ===============================================================

# create instance of an 8480-SC POD device

port: str = ChoosePort()
pod = POD_8480SC(port)

# write each command:

print('~~ BASICS ~~')
RunCommand(pod, 'PING') # Used to verify device is present and communicating
RunCommand(pod, 'TYPE') # Returns the device type value.  This is a unique value for each device.  For the 8480SC it is 0x32
RunCommand(pod, 'FIRMWARE VERSION') # Returns the device firmware version as 3 values.  So 1.0.10 would come back as 0x31, 0x30, 0x00, 0x41

print('~~ STIMULUS ~~')
RunCommand(pod, 'SET STIMULUS', (0, 1000, 0, 500, 0, 5, 5)) # Sets the stimulus configuration on the selected channel. See format below.
RunCommand(pod, 'GET STIMULUS', (0)) # Requires U8 Channel. Gets the current stimulus configuration for the selected channel. See format below.

print('~~ TTL SETUP ~~')
RunCommand(pod, 'SET TTL SETUP', (0,128,25)) # Sets the TTL setup for the channel. Format is Channel, Config Flags, Debounce in ms. See below for config flags format
RunCommand(pod, 'GET TTL SETUP', (0)) # Requires U8 channel. Returns U8 config flags, and U8 debounce value in ms. See below for config flags format

print('~~ SYNC CONFIG ~~')
RunCommand(pod, 'SET SYNC CONFIG', (5)) # Sets the sync config byte.  See format below
RunCommand(pod, 'GET SYNC CONFIG', ()) # Gets the sync config byte.  See format below

print('~~ LED CURRENT ~~')
RunCommand(pod, 'SET LED CURRENT', (0, 25)) # Requires U8 channel. Sets the selected channel LED current to the given value in mA, from 0-600
RunCommand(pod, 'SET LED CURRENT', (1, 26)) # Requires U8 channel. Sets the selected channel LED current to the given value in mA, from 0-600
RunCommand(pod, 'GET LED CURRENT', ()) # Gets the setting for LED current for both channels in mA. CH0 CH1

print('~~ ESTIM CURRENT ~~')
RunCommand(pod, 'SET ESTIM CURRENT', (0, 22)) # Requires U8 channel. Sets the selected chanenl ESTIM current to the given value in percentage, from 0-100
RunCommand(pod, 'SET ESTIM CURRENT', (1, 23)) # Requires U8 channel. Sets the selected chanenl ESTIM current to the given value in percentage, from 0-100
RunCommand(pod, 'GET ESTIM CURRENT', ()) # Gets the setting for the ESTIM current for both channels, in percentage. CH0 then CH1

print('~~ PREAMP TYPE ~~')
RunCommand(pod, 'SET PREAMP TYPE', (2)) # Sets the preamp value, from 0-1023.  This should match the table in Sirenia, it's a 10-bit code that tells the 8401 what preamp is connected.  Only needed when used with an 8401. See table below.
RunCommand(pod, 'GET PREAMP TYPE', ()) # Gets the store preamp value

print('~~ TTL PULLUPS ~~')
RunCommand(pod, 'SET TTL PULLUPS', (1)) # Sets whether pullups are enabled on the TTL lines.  0 = pullups disabled, non-zero = pullups enabled
RunCommand(pod, 'GET TTL PULLUPS', ()) # Gets whether TTL pullups are enabled on the TTL lines.  0 = no pullups, non-zero = pullups enabled

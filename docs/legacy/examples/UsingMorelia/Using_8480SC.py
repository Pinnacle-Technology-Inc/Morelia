"""Runs all commands for an 8480-SC POD device.
"""

# add directory path to code 
import Path 
Path.AddAPIpath()

# local imports
import  HelperFunctions as hf
from    Morelia.Devices  import Pod8480SC

# authorship
__author__      = "Sree Kondi"
__maintainer__  = "Sree Kondi"
__credits__     = ["Sree Kondi","Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

# create instance of an 8480-SC POD device

port: str = Pod8480SC.ChoosePort()
pod = Pod8480SC(port)

# write each command:

print('~~ BASICS ~~')
hf.RunCommand(pod, 'PING') # Used to verify device is present and communicating
hf.RunCommand(pod, 'TYPE') # Returns the device type value.  This is a unique value for each device.  For the 8480SC it is 0x32
hf.RunCommand(pod, 'FIRMWARE VERSION') # Returns the device firmware version as 3 values.  So 1.0.10 would come back as 0x31, 0x30, 0x00, 0x41

print('~~ STIMULUS ~~')
hf.RunCommand(pod, 'SET STIMULUS', (0, 1000, 0, 500, 0, 5, 5)) # Sets the stimulus configuration on the selected channel. See format below.
hf.RunCommand(pod, 'GET STIMULUS', (0)) # Requires U8 Channel. Gets the current stimulus configuration for the selected channel. See format below.

print('~~ TTL SETUP ~~')
hf.RunCommand(pod, 'SET TTL SETUP', (0,128,25)) # Sets the TTL setup for the channel. Format is Channel, Config Flags, Debounce in ms. See below for config flags format
hf.RunCommand(pod, 'GET TTL SETUP', (0)) # Requires U8 channel. Returns U8 config flags, and U8 debounce value in ms. See below for config flags format

print('~~ SYNC CONFIG ~~')
hf.RunCommand(pod, 'SET SYNC CONFIG', (5)) # Sets the sync config byte.  See format below
hf.RunCommand(pod, 'GET SYNC CONFIG', ()) # Gets the sync config byte.  See format below

print('~~ LED CURRENT ~~')
hf.RunCommand(pod, 'SET LED CURRENT', (0, 25)) # Requires U8 channel. Sets the selected channel LED current to the given value in mA, from 0-600
hf.RunCommand(pod, 'SET LED CURRENT', (1, 26)) # Requires U8 channel. Sets the selected channel LED current to the given value in mA, from 0-600
hf.RunCommand(pod, 'GET LED CURRENT', ()) # Gets the setting for LED current for both channels in mA. CH0 CH1

print('~~ ESTIM CURRENT ~~')
hf.RunCommand(pod, 'SET ESTIM CURRENT', (0, 22)) # Requires U8 channel. Sets the selected chanenl ESTIM current to the given value in percentage, from 0-100
hf.RunCommand(pod, 'SET ESTIM CURRENT', (1, 23)) # Requires U8 channel. Sets the selected chanenl ESTIM current to the given value in percentage, from 0-100
hf.RunCommand(pod, 'GET ESTIM CURRENT', ()) # Gets the setting for the ESTIM current for both channels, in percentage. CH0 then CH1

print('~~ PREAMP TYPE ~~')
hf.RunCommand(pod, 'SET PREAMP TYPE', (2)) # Sets the preamp value, from 0-1023.  This should match the table in Sirenia, it's a 10-bit code that tells the 8401 what preamp is connected.  Only needed when used with an 8401. See table below.
hf.RunCommand(pod, 'GET PREAMP TYPE', ()) # Gets the store preamp value

print('~~ TTL PULLUPS ~~')
hf.RunCommand(pod, 'SET TTL PULLUPS', (1)) # Sets whether pullups are enabled on the TTL lines.  0 = pullups disabled, non-zero = pullups enabled
hf.RunCommand(pod, 'GET TTL PULLUPS', ()) # Gets whether TTL pullups are enabled on the TTL lines.  0 = no pullups, non-zero = pullups enabled
"""
Example that demonstrates how to use Morelia.Stream to save streaming \
data to a file from a 8206-HR POD device. 
"""

# add directory path to code 
import Path 
Path.AddAPIpath()

# local imports
from Morelia.Devices import Pod8206HR
from Morelia.Packets import PacketStandard, Packet
from Morelia.Stream.Collect import Bucket, DrainBucket, Valve

# enviornment imports
from threading import Thread

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

# choose port for the 8206-HR device
port = Pod8206HR.ChoosePort()

# create object to control the 8206-HR device
pod  = Pod8206HR(port, 10)

# set the sample rate of the device 
samplerate = 100
w : PacketStandard = pod.WriteRead('SET SAMPLE RATE', samplerate)

r = Valve.GetStopBytes(self)
print("!!!,", r)

# if(  not isinstance(r,Packet)) :                return TestResult(False, 'Command did not return a packet')
# elif(not isinstance(r,PacketStandard)) :        return TestResult(False, 'Command did not return a standard packet')
# elif(r.CommandNumber()  != 127     ) :          return TestResult(False, 'Packet has an incorrect command number.')
# elif(r.Payload()        != None ) :             return TestResult(False, 'Packet has incorrect payload.')

# if(not isinstance(r,Packet)) :        print ('Command did not return a standard packet')

if(r.Payload        != None ) :             print('Packet has incorrect payload.')


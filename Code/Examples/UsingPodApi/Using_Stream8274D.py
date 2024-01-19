"""
Example that demonstrates how to use PodApi.Stream to save streaming \
data to a file from a 8206-HR POD device. 
"""

# add directory path to code 
import Path 
Path.AddAPIpath()

# local imports
import  HelperFunctions as hf
from PodApi.Devices import Pod8274D
from PodApi.Packets import PacketStandard
from PodApi.Stream.Collect import Bucket, DrainBucket

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
port: str = Pod8274D.ChoosePort()
pod = Pod8274D(port)



# set the sample rate of the device 
# samplerate = 100
# w : PacketStandard = pod.WriteRead('SET SAMPLE RATE', samplerate)

print('~~ CONNECT BY ADDRESS ~~')
hf.RunCommand(pod, 'CONNECT BY ADDRESS', (0, 13, 111, 254, 61, 150)) 


# set file name. Must input a text or EDF file extension
file : str  = input('File name (.txt/.csv/.edf): ')

# create objects to collect and save streaming data 
bkt : Bucket = Bucket(pod)
drn : DrainBucket = DrainBucket(bkt, file)

# get number of seconds to collect data for
nSec : float = float(input('Number of seconds to stream data: '))
if(nSec < 1.2 ) : nSec = 1.2 

# start collecting data and saving to file 
bucketThread : Thread = bkt.StartCollecting(nSec)
drainThread  : Thread = drn.DrainBucketToFile()
print('Starting data collection...')

# wait for threads to finish
bucketThread.join() 
print('Streaming finished')
drainThread.join()
print('Saving finished')

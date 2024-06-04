"""
Example that demonstrates how to use Morelia.Stream to save streaming \
data to a file from a 8206-HR POD device. 
"""

# add directory path to code 
import Path 
Path.AddAPIpath()

# local imports
from Morelia.Devices import Pod8206HR
from Morelia.Packets import PacketStandard
from Morelia.Stream.Collect import Bucket, DrainBucket

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
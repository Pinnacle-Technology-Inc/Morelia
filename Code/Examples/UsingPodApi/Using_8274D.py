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



print('~~ CONNECT BY ADDRESS ~~')
hf.RunCommand(pod, 'CONNECT BY ADDRESS', (0, 13, 111, 254, 61, 150)) 


print('~~ GET NAME ~~')
hf.RunCommand(pod, 'GET NAME', ()) 

print('~~ GET SAMPLE RATE ~~')
hf.RunCommand(pod, 'GET SAMPLE RATE', ()) 

print('~~ STREAM ~~')
hf.RunCommand(pod, 'STREAM', (1,)) 
hf.RunCommand(pod, 'STREAM', (0,)) 



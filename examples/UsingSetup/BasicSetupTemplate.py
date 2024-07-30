"""
Simple example template that runs SetupPodDevices. 
"""

# add directory path to code 
import Path 
Path.AddAPIpath()

# local imports
from Setup.SetupAllDevices import SetupAll

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

# ===============================================================

# setup POD devices for streaming
go = SetupAll()
go.Run()

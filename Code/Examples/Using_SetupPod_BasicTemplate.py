"""
Simple example template that runs SetupPodDevices. 
"""

# add directory path to code 
import sys, os
aroundApi = os.path.abspath('.').split('Python-POD-API')
apiPath = aroundApi[0] + 'Python-POD-API'
if(len(aroundApi) > 1 and (not aroundApi[1].startswith('\\'))): apiPath += aroundApi[1].split('\\')[0]
sys.path.insert(0, os.path.join( apiPath, 'Code', 'API_Modules') )

# local imports
from Setup_PodDevices import Setup_PodDevices

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

# ===============================================================

# setup POD devices for streaming
go = Setup_PodDevices()
go.Run()
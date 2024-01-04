# enviornment imports
from Testing import T_PodApi

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

def RunTests() : 
    # T_PodApi.T_Parameters.TestAll .RunTests( True, False )
    # T_PodApi.T_Commands.TestAll   .RunTests( True, False )
    T_PodApi.T_Packets.TestAll    .RunTests( True, True )


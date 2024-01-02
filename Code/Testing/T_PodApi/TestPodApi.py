# enviornment imports
from Testing.T_PodApi import T_Parameters, T_Commands

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

def RunTests() : 
    T_Parameters.TestAllParams.RunTests(True, True)
    # T_Commands.T_PodCommands.RunTests()
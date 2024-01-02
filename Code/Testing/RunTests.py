# add directory path to code 
import Path
Path.AddAPIpath()

# enviornment imports
from Testing.T_PodApi import T_Parameters

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"


# # top
T_Parameters.TestAllParams.RunTests()

# # individual 
# T_Parameters.T_ParamsBasic.RunTests()
# T_Parameters.T_Params8206HR.RunTests()
# T_Parameters.T_Params8401HR.RunTests()
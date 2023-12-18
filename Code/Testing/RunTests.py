# add directory path to code 
import Path
Path.AddAPIpath()

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"



from T_PodApi.T_Parameters import T_ParamsBasic
from T_PodApi.T_Parameters import T_Params8206HR

T_ParamsBasic.RunTests()
T_Params8206HR.RunTests()
# local imports
from Testing.T_PodApi.T_Parameters import T_ParamsBasic, T_Params8206HR, T_Params8401HR

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

def RunTests(printTests: bool = True) : 
    print("==== PodApi.Parameters ====")
    tests = [
        T_ParamsBasic.RunTests(printTests),
        T_Params8206HR.RunTests(printTests),
        T_Params8401HR.RunTests(printTests),
    ]
    # count totals
    passed = sum([x[0] for x in tests])
    total  = sum([x[1] for x in tests])
    print("== Passed "+str(passed)+" of "+str(total)+" ==")

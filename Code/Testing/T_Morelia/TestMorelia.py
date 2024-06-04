# enviornment imports
from Testing import T_Morelia

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

def RunTests(printThisTest = True) -> tuple[int,int]: 
    if(printThisTest) : print("====== Morelia ======")
    # run all tests 
    tests : list[tuple[int,int]] = [
        T_Morelia.T_Parameters.TestAll .RunTests( True, True ),
        T_Morelia.T_Commands.TestAll   .RunTests( True, True ),
        T_Morelia.T_Packets.TestAll    .RunTests( True, True ),
        T_Morelia.T_Devices.TestAll    .RunTests( True, True ),
        T_Morelia.T_Devices.T_SerialPorts.TestAll  .RunTests( True, True )
    ]
    # count totals
    passed = sum([x[0] for x in tests])
    total  = sum([x[1] for x in tests])
    # show passed total 
    if(printThisTest) : print("====== Passed "+str(passed)+" of "+str(total)+" ======")
    # finish
    print("====== DONE ======")
    return (passed, total)   

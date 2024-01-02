# local imports
from Testing.T_PodApi import T_Parameters

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

def RunTests(printThisTest: bool = False, printSubTests: bool = True) -> tuple[int,int] :
    """Run all tests for PodApi.Parameters

    Args:
        printThisTest (bool, optional): Prints a header and number of total tests passed when True. Defaults to False.
        printSubTests (bool, optional): Prints a header and number of tests passed for each sub-test when True. Defaults to True.

    Returns:
        tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
    """
    # show header 
    if(printThisTest) : print("==== PodApi.Parameters ====")
    # list all tests
    sub = printSubTests and printThisTest # is false if either are false
    tests = [
        T_Parameters.T_ParamsBasic.RunTests(sub),
        T_Parameters.T_Params8206HR.RunTests(sub),
        T_Parameters.T_Params8401HR.RunTests(sub),
        T_Parameters.T_Params8229.RunTests(sub),
        T_Parameters.T_Params8480SC.RunTests(sub),
    ]
    # count totals
    passed = sum([x[0] for x in tests])
    total  = sum([x[1] for x in tests])
    # show passed total 
    if(printThisTest) : print("== Passed "+str(passed)+" of "+str(total)+" ==")
    # finish
    return (passed, total)   
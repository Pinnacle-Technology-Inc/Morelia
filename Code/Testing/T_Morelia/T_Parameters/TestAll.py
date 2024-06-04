# local imports
from Testing.T_Morelia.TestProtocol import RunningTests
from Testing.T_Morelia import T_Parameters

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

def RunTests(printThisTest: bool = False, printSubTests: bool = True) -> tuple[int,int] :
    """Run all tests for Morelia.Parameters

    Args:
        printThisTest (bool, optional): Prints a header and number of total tests passed when True. Defaults to False.
        printSubTests (bool, optional): Prints a header and number of tests passed for each sub-test when True. Defaults to True.

    Returns:
        tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
    """
    return RunningTests.RunAllTests(
        testModules   = [
                T_Parameters.T_ParamsBasic,
                T_Parameters.T_Params8206HR,
                T_Parameters.T_Params8401HR,
                T_Parameters.T_Params8229,
                T_Parameters.T_Params8480SC,
            ], 
        headerModule  = 'Morelia.Parameters', 
        printThisTest = printThisTest, 
        printSubTests = printSubTests
    )

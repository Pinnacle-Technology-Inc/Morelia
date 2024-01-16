# local imports
from Testing.T_PodApi.TestProtocol import RunningTests
from Testing.T_PodApi import T_Devices

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

def RunTests(printThisTest: bool = False, printSubTests: bool = True) -> tuple[int,int] :
    """Run all tests for PodApi.Devices

    Args:
        printThisTest (bool, optional): Prints a header and number of total tests passed when True. Defaults to False.
        printSubTests (bool, optional): Prints a header and number of tests passed for each sub-test when True. Defaults to True.

    Returns:
        tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
    """
    return RunningTests.RunAllTests(
        testModules   = [
            T_Devices.T_PodDevice_8206HR,
        ], 
        headerModule  = 'PodApi.Devices', 
        printThisTest = printThisTest, 
        printSubTests = printSubTests
    )
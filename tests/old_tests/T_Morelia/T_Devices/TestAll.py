# local imports
from Testing.T_Morelia.TestProtocol import RunningTests
from Testing.T_Morelia import T_Devices

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert", "James Hurd"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

def RunTests(printThisTest: bool = False, printSubTests: bool = True) -> tuple[int,int] :
    """Run all tests for Morelia.Devices

    Args:
        printThisTest (bool, optional): Prints a header and number of total tests passed when True. Defaults to False.
        printSubTests (bool, optional): Prints a header and number of tests passed for each sub-test when True. Defaults to True.

    Returns:
        tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
    """
    testModulesList : list = []
    forbidden = []

    testModulesList.append(T_Devices.T_PodDevice_8206HR.T_Pod8206HR(forbidden=forbidden))
    forbidden.append(testModulesList[-1].port)

    testModulesList.append(T_Devices.T_PodDevice_8401HR.T_Pod8401HR(forbidden=forbidden))
    forbidden.append(testModulesList[-1].port)

    testModulesList.append(T_Devices.T_PodDevice_8229.T_Pod8229(forbidden=forbidden))
    forbidden.append(testModulesList[-1].port)

    testModulesList.append(T_Devices.T_PodDevice_8480SC.T_Pod8480SC(forbidden=forbidden))
    forbidden.append(testModulesList[-1].port)

    testModulesList.append(T_Devices.T_PodDevice_8274D.T_Pod8274D(forbidden=forbidden))
    forbidden.append(testModulesList[-1].port)


    return RunningTests.RunAllTests(
        testModules   = testModulesList, 
        headerModule  = 'Morelia.Devices', 
        printThisTest = printThisTest, 
        printSubTests = printSubTests
    )

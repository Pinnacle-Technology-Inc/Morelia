# local imports
from Testing.T_Morelia.TestProtocol import RunningTests
from Testing.T_Morelia.T_Devices import T_SerialPorts

# authorship
__author__      = "James Hurd"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert", "James Hurd"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

def RunTests(printThisTest: bool = False, printSubTests: bool = True) -> tuple[int,int] :
    """Run all tests for Morelia.Devices.SerialPorts

    Args:
        printThisTest (bool, optional): Prints a header and number of total tests passed when True. Defaults to False.
        printSubTests (bool, optional): Prints a header and number of tests passed for each sub-test when True. Defaults to True.

    Returns:
        tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
    """


    testModulesList = [T_SerialPorts.T_SerialComm.T_PortIO()]

    return RunningTests.RunAllTests(
            testModules = testModulesList,
            headerModule = 'Morelia.Devices.SerialPorts',
            printThisTest = printThisTest,
            printSubTests = printSubTests
        )


# local imports
from Testing.T_PodApi.TestProtocol import RunningTests, TestResult

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

# ---------------------------------------------------------------------------------------------------------
def RunTests(printTests: bool = True) -> tuple[int,int]: 
    """Run all tests on PodApi.Packets.PacketStandard

    Args:
        printTests (bool, optional): Make True to print the test results and messages. Defaults to True.
    
    Returns:
        tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
    """
    # collect all tests
    tests = {
        "1. Construct:\t\t"    : Construct,
    }
    return RunningTests.RunTests(tests, 'PacketStandard', printTests=printTests)
# ---------------------------------------------------------------------------------------------------------


def Construct() -> TestResult : 
    print('hello world')
    return TestResult(True)
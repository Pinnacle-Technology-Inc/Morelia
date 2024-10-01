# enviornment imports
from typing import Callable

# local imports
from Testing.T_Morelia.TestProtocol.TestResult import TestResult

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"


def RunAllTests(
        testModules   : list, 
        headerModule  : str = '', 
        printThisTest : bool = False, 
        printSubTests : bool = True
    ) -> tuple[int,int] :
    """Run all tests for a given API module.

    Args:
        testModules (list): List of test modules to call RunTests() on.
        headerModule (str, optional): Text to print as the section header (i.e. 'Morelia.Parameters').
        printThisTest (bool, optional): Prints a header and number of total tests passed when True. Defaults to False.
        printSubTests (bool, optional): Prints a header and number of tests passed for each sub-test when True. Defaults to True.

    Returns:
        tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
    """
    # show header 
    if(printThisTest) : print("==== "+str(headerModule)+" ====")
    # list all tests
    tests = [ mod.RunTests(printSubTests) for mod in testModules ]
    # count totals
    passed = sum([x[0] for x in tests])
    total  = sum([x[1] for x in tests])
    # show passed total 
    if(printThisTest) : print("==== Passed "+str(passed)+" of "+str(total)+" ====")
    # finish
    return (passed, total)   

def RunTests(tests: dict[str, Callable], headerTitle: str, headerWrap: str = '==', printTests: bool = True) -> tuple[int,int]: 
    """Run all tests on a given class.

    Args:
        printTests (bool, optional): Make True to print the test results and messages. Defaults to True.
    
    Returns:
        tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
    """
    # run all 
    runtests: dict[str,TestResult] = {key : _ErrorWrap(val) for (key,val) in tests.items()}
    # get total status 
    passed = sum([int(x.result) for x in runtests.values()])
    total = len(runtests.keys())
    # show results 
    if(printTests) : 
        print(str(headerWrap)+" Testing: "+str(headerTitle)+" "+str(headerWrap))
        [print(key, val.Result(), val.Note()) for (key,val) in runtests.items()]
        print(str(headerWrap)+" Passed "+str(passed)+" of "+str(total)+" "+str(headerWrap))
    return (passed, total)  

def _ErrorWrap(function) -> TestResult : 
    try :
        return function()
    except Exception as e :
        return TestResult(False, "Unexpected Exception: "+str(e))
# local imports
from typing import Callable

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

def RunTests(tests: dict[str, Callable], headerTitle: str, headerWrap: str = '==', printTests: bool = True) -> tuple[int,int]: 
    """Run all tests on a given class.

    Args:
        printTests (bool, optional): Make True to print the test results and messages. Defaults to True.
    
    Returns:
        tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
    """
    # run all 
    runtests: dict[str,tuple[bool,str]] = {key : _ErrorWrap(val) for (key,val) in tests.items()}
    # get total status 
    passed = sum([int(x[0]) for x in runtests.values()])
    total = len(runtests.keys())
    # show results 
    if(printTests) : 
        print(str(headerWrap)+" Testing: "+str(headerTitle)+" "+str(headerWrap))
        [print(key, val[0], val[1]) for (key,val) in runtests.items()]
        print(str(headerWrap)+" Passed "+str(passed)+" of "+str(total)+" "+str(headerWrap))
    return (passed, total)  

def _ErrorWrap(function) : 
    try : 
        return (function())
    except Exception as e :
        return (False, ' - Unexpected Exception: '+str(e))
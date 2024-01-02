# local imports
import PodApi

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

def RunTests(printTests: bool = True) -> tuple[int,int]: 
    """Run all tests on PodApi.Parameters.Params

    Args:
        printTests (bool, optional): Make True to print the test results and messages. Defaults to True.
    
    Returns:
        tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
    """
    # collect all tests
    tests = {
        "1. Match Init:\t"  : Test1_MatchInit,
        "2. Check Port:\t"    : Test2_BadPort
    }
    # run all 
    tests: dict[str,tuple[bool,str]] = {key : _ErrorWrap(val) for (key,val) in tests.items()}
    # get total status 
    passed = sum([int(x[0]) for x in tests.values()])
    total = len(tests.keys())
    # show results 
    if(printTests) : 
        print("== Testing: PodApi.Parameters.Params ==")
        [print(key, val[0], val[1]) for (key,val) in tests.items()]
        print("Passed "+str(passed)+" of "+str(total))
    return (passed, total)   
    
def Test1_MatchInit() -> tuple[bool,str] : 
    """Tests if the port argument given to a Params object is correctly reflected in its GetInit() result. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    # identify inputs and outputs from Params class 
    INport: str = "COM1"
    INcheckForValidParams: bool = False
    OUTexpectedInitStr: str = "PodApi.Parameters.Params(port='"+INport+"')"
    # create instance of params
    param = PodApi.Parameters.Params(INport, INcheckForValidParams)
    # get init build string
    paraminits = param.GetInit()
    # check that result matches expected 
    if(paraminits == OUTexpectedInitStr) :  return (True, '')
    return ( False, " - GetInit does not match given arguments.\n\tExpected: "+OUTexpectedInitStr+"\n\tRecieved: "+str(paraminits) )

def Test2_BadPort() : 
    """Tests if the Params object correctly raises an Exception when it recieves a bad 'port' string argument. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    # identify inputs and outputs from Params class 
    INport: str = "thisIsBadPort"
    INcheckForValidParams: bool = True
    try : 
        # create instance of params. this should raise an Exception 
        param = PodApi.Parameters.Params(INport, INcheckForValidParams)
        return (False, " - Params did not notice the invalid 'port' argument.")
    except Exception as e : 
        return(True, '')    
    
def _ErrorWrap(function) : 
    try : 
        return (function())
    except Exception as e :
        return (False, ' - Unexpected Exception: '+str(e))

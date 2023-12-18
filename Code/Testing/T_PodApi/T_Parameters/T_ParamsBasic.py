# local imports
import PodApi

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

def RunTests() : 
    print("== Testing: PodApi.Parameters.Params ==")
    # collect all tests
    tests = {
        "1. Match Init:\t"  : Test1_MatchInit,
        "2. Bad Path:\t"    : Test2_BadPath
    }
    tests: dict[str,tuple[bool,str]] = {key : _ErrorWrap(val) for (key,val) in tests.items()}
    # show results 
    passed: int = 0
    for key,val in tests.items() : 
        print(key, val[0], val[1])
        passed += int(val[0]) # increment by 1 if passed 
    # show total status 
    print("Passed "+str(passed)+" of "+str(len(tests.keys())))    
    
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
    return ( False, " - GetInit does not match given arguments.\nExpected: "+OUTexpectedInitStr+" \nRecieved: "+str(paraminits) )

def Test2_BadPath() : 
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

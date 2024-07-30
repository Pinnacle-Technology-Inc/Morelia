# local imports
from Morelia.Parameters import Params
from Testing.T_Morelia.TestProtocol import RunningTests, TestResult

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

def RunTests(printTests: bool = True) -> tuple[int,int]: 
    """Run all tests on Params

    Args:
        printTests (bool, optional): Make True to print the test results and messages. Defaults to True.
    
    Returns:
        tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
    """
    
    # collect all tests
    tests = {
        "1. Match Init:\t\t"    : Test1_MatchInit,
        "2. Check Port:\t\t"    : Test2_BadPort
    }
    return RunningTests.RunTests(tests, 'Params', printTests=printTests)
    
def Test1_MatchInit() -> TestResult : 
    """Tests if the port argument given to a Params object is correctly reflected in its GetInit() result. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    # identify inputs and outputs from Params class 
    INport: str = "COM1"
    INcheckForValidParams: bool = False
    OUTexpectedInitStr: str = "Morelia.Parameters.Params(port='"+INport+"')"
    # create instance of params
    param = Params(INport, INcheckForValidParams)
    # get init build string
    paraminits = param.GetInit()
    # check that result matches expected 
    if(paraminits == OUTexpectedInitStr) :  return TestResult(True, '')
    return TestResult( False, "GetInit does not match given arguments.\n\tExpected: "+OUTexpectedInitStr+"\n\tRecieved: "+str(paraminits) )

def Test2_BadPort() -> TestResult: 
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
        param = Params(INport, INcheckForValidParams)
        return TestResult(False, "Params did not notice the invalid 'port' argument.")
    except Exception as e : 
        return TestResult(True, '')    
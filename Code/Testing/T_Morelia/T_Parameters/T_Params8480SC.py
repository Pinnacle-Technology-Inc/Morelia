# local imports
from Morelia.Parameters import Params8480SC
from Testing.T_Morelia.TestProtocol import RunningTests, TestResult

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"


def RunTests(printTests: bool = True) -> tuple[int,int]: 
    """Run all tests on Params8480SC

    Args:
        printTests (bool, optional): Make True to print the test results and messages. Defaults to True.
    
    Returns:
        tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
    """
    # collect all tests
    tests = {
        "1. Match Init:\t\t"    : Test1_MatchInit,
        "2. Check Preamp:\t"    : Test2_BadPreamp,
        "3. Check LED:\t\t"     : Test3_BadLedCurrent,
        "4. Check Estim:\t\t"   : Test4_BadEstimCurrent,
    }
    return RunningTests.RunTests(tests, 'Params8480SC', printTests=printTests)

def Test1_MatchInit() : 
    """Tests if the port argument given to a Params8480SC object is correctly reflected in its GetInit() result. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    # create instance of Params8206HR with valid arguments 
    param = Params8480SC(
        port = 'COM1',
        stimulus = (0, 1000, 0, 500, 0, 5, 5),
        preamp = 1,
        ledCurrent = (25, 30),
        ttlPullups = 0,
        estimCurrent = (25, 50),
        syncConfig = 5,
        ttlSetup = (0, 0),             
        checkForValidParams = False
    )
    # get init build string
    paraminits = param.GetInit()
    # check that result matches expected 
    OUTexpectedInitStr: str = "Morelia.Parameters.Params8401HR(port='COM1', preamp='1', ledCurrent=(25, 30), ttlPullups=0, estimCurrent=(25, 50), syncConfig=5, ttlSetup=(0, 0))"
    if(paraminits == OUTexpectedInitStr) :  return TestResult(True, '')
    return TestResult( False, "GetInit does not match given arguments.\n\tExpected: "+OUTexpectedInitStr+"\n\tRecieved: "+str(paraminits) )

def Test2_BadPreamp() : 
    """Tests if the Params8480SC object correctly raises an Exception when it recieves a bad 'preamp' argument. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    try : 
        # create instance of Params8401HR
        param = Params8480SC(
            port = 'COM1',
            stimulus = (0, 1000, 0, 500, 0, 5, 5),
            preamp = 1024, # 1
            ledCurrent = (25, 30),
            ttlPullups = 0,
            estimCurrent = (25, 50),
            syncConfig = 5,
            ttlSetup = (0, 0),       
            checkForValidParams = True
        )
        return TestResult(False, "Params8401HR did not notice the invalid 'preamp' argument.")
    except Exception as e : 
        return TestResult(True, '')
    
def Test3_BadLedCurrent() : 
    """Tests if the Params8480SC object correctly raises an Exception when it recieves a bad 'ledCurrent' argument. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    try : 
        # create instance of Params8401HR
        param = Params8480SC(
            port = 'COM1',
            stimulus = (0, 1000, 0, 500, 0, 5, 5),
            preamp = 1024, # 1
            ledCurrent = (-1,601), # (25, 30),
            ttlPullups = 0,
            estimCurrent = (25, 50),
            syncConfig = 5,
            ttlSetup = (0, 0),       
            checkForValidParams = True
        )
        return TestResult(False, "Params8401HR did not notice the invalid 'ledCurrent' argument.")
    except Exception as e : 
        return TestResult(True, '')
    
def Test4_BadEstimCurrent() : 
    """Tests if the Params8480SC object correctly raises an Exception when it recieves a bad 'estimCurrent' argument. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    try : 
        # create instance of Params8401HR
        param = Params8480SC(
            port = 'COM1',
            stimulus = (0, 1000, 0, 500, 0, 5, 5),
            preamp = 1024, # 1
            ledCurrent = (25, 30),
            ttlPullups = 0,
            estimCurrent = (-1, 101),
            syncConfig = 5,
            ttlSetup = (0, 0),       
            checkForValidParams = True
        )
        return TestResult(False, "Params8401HR did not notice the invalid 'estimCurrent' argument.")
    except Exception as e : 
        return TestResult(True, '')

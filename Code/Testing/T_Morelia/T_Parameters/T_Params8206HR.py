# local imports
from Morelia.Parameters import Params8206HR
from Testing.T_Morelia.TestProtocol import RunningTests, TestResult

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

def RunTests(printTests: bool = True) -> tuple[int,int]: 
    """Run all tests on Morelia.Parameters.Params8206HR

    Args:
        printTests (bool, optional): Make True to print the test results and messages. Defaults to True.
    
    Returns:
        tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
    """
    # collect all tests
    tests = {
       "1. Match Init:\t\t"   : Test1_MatchInit,
       "2. Check Port:\t\t"     : Test2_BadPort,
       "3. Check Sample Rate:\t" : Test3_BadSampleRate,
       "4. Check Preamp Gain:\t" : Test4_BadPreamp,
       "5. Check Low Pass:\t" : Test5_BadLowPass,
    }
    return RunningTests.RunTests(tests, 'Params8206HR', printTests=printTests)

def Test1_MatchInit() : 
    """Tests if the port argument given to a Params8206HR object is correctly reflected in its GetInit() result. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    # create instance of Params8206HR with valid arguments 
    param = Params8206HR(
            port = 'COM1',
            sampleRate = 500,
            preamplifierGain = 10,
            lowPass = (400,400,400),
            checkForValidParams = False
        )
    # get init build string
    paraminits = param.GetInit()
    # check that result matches expected 
    OUTexpectedInitStr: str = "Morelia.Parameters.Params8206HR(port='COM1', sampleRate=500, preamplifierGain=10, lowPass=(400, 400, 400))"
    if(paraminits == OUTexpectedInitStr) :  return TestResult(True, '')
    return TestResult( False, "GetInit does not match given arguments.\n\tExpected: "+OUTexpectedInitStr+"\n\tRecieved: "+str(paraminits) )

def Test2_BadPort() : 
    """Tests if the Params8206HR object correctly raises an Exception when it recieves a bad 'port' string argument. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    try : 
        # create instance of Params8206HR
        param = Params8206HR(
                    port = 'BAD_PORT', # !
                    sampleRate = 500,
                    preamplifierGain = 10,
                    lowPass = (400,400,400),
                    checkForValidParams = True
                )
        return TestResult(False, "Params8206HR did not notice the invalid 'port' argument.")
    except Exception as e : 
        return TestResult(True, '')   
    
def Test3_BadSampleRate() : 
    """Tests if the Params8206HR object correctly raises an Exception when it recieves a bad 'sampleRate' integer argument. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    try : 
        # create instance of Params8206HR
        param = Params8206HR(
                    port = 'COM1',
                    sampleRate = 0, # !
                    preamplifierGain = 10,
                    lowPass = (400,400,400),
                    checkForValidParams = True
                )
        return TestResult(False, "Params8206HR did not notice the invalid 'sampleRate' argument.")
    except Exception as e : 
        return TestResult(True, '')
    
    
def Test4_BadPreamp() : 
    """Tests if the Params8206HR object correctly raises an Exception when it recieves a bad 'preamplifierGain' integer argument. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    # identify inputs and outputs from Params8206HR class 
    try : 
        # create instance of Params8206HR
        param = Params8206HR(
                    port = 'COM1',
                    sampleRate = 500, 
                    preamplifierGain = 0, # !
                    lowPass = (400,400,400),
                    checkForValidParams = True
                )
        return TestResult(False, "Params8206HR did not notice the invalid 'preamplifierGain' argument.")
    except Exception as e : 
        return TestResult(True, '')   
    

def Test5_BadLowPass() : 
    """Tests if the Params8206HR object correctly raises an Exception when it recieves a bad 'lowPass' integer argument. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    try : 
        # create instance of Params8206HR
        param = Params8206HR(
                    port = 'COM1',
                    sampleRate = 500, 
                    preamplifierGain = 0,
                    lowPass = (0,9,600), # !
                    checkForValidParams = True
                )
        return TestResult(False, "Params8206HR did not notice the invalid 'lowPass' argument.")
    except Exception as e : 
        return TestResult(True, '')   
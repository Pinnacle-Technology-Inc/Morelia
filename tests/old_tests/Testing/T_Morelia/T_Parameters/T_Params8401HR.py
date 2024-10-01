# local imports
from Morelia.Parameters import Params8401HR
from Testing.T_Morelia.TestProtocol import RunningTests, TestResult

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"


def RunTests(printTests: bool = True) -> tuple[int,int]: 
    """Run all tests on Params8401HR

    Args:
        printTests (bool, optional): Make True to print the test results and messages. Defaults to True.
    
    Returns:
        tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
    """
    # collect all tests
    tests = {
       "1. Match Init:\t\t"      : Test1_MatchInit,
       "2. Check Port:\t\t"      : Test2_BadPort,
       "3. Check Preamp Dev:\t"  : Test3_BadPreampDev,
       "4. Check Sample Rate:\t" : Test4_BadSampleRate,
       "5. Check Preamp Gain:\t" : Test5_BadPreampGain,
       "6. Check ssGain:\t"      : Test6_BadSsGain, 
       "7. Check High Pass:\t"   : Test7_BadHighPass,
       "8. Check Low Pass:\t"    : Test8_BadLowPass,
       "9. Check Bias:\t\t"      : Test9_BadBias,
       "10. Check DC Mode:\t"    : Test10_BadDcMode
    }
    return RunningTests.RunTests(tests, 'Params8401HR', printTests=printTests)
    

def Test1_MatchInit() : 
    """Tests if the port argument given to a Params8401HR object is correctly reflected in its GetInit() result. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    # create instance of Params8206HR with valid arguments 
    param = Params8401HR(
            port            = 'COM1',
            preampDevice    = '8407-SE',            
            sampleRate      = 3000,            
            muxMode         = False,           
            preampGain      = (None, 10, 100, None),   
            ssGain          = (1, 1, 5, 5),   
            highPass        = (0, 0.5, 1, 10),   
            lowPass         = (100, 1000, 10000, 15000),   
            bias            = (0.6, -0.6, 1.0, -1.0),   
            dcMode          = ('VBIAS', 'AGND', 'VBIAS', 'AGND'),   
            checkForValidParams = False
        )
    # get init build string
    paraminits = param.GetInit()
    # check that result matches expected 
    OUTexpectedInitStr: str = "Morelia.Parameters.Params8401HR(port='COM1', preampDevice='8407-SE', sampleRate=3000, muxMode=False, preampGain=(None, 10, 100, None), ssGain=(1, 1, 5, 5), highPass=(0.0, 0.5, 1.0, 10.0), lowPass=(100, 1000, 10000, 15000), bias=(0.6, -0.6, 1.0, -1.0), dcMode=('VBIAS', 'AGND', 'VBIAS', 'AGND'))"
    if(paraminits == OUTexpectedInitStr) :  return TestResult(True, '')
    return TestResult( False, "GetInit does not match given arguments.\n\tExpected: "+OUTexpectedInitStr+"\n\tRecieved: "+str(paraminits) )


def Test2_BadPort() : 
    """Tests if the Params8401HR object correctly raises an Exception when it recieves a bad 'port' argument. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    try : 
        # create instance of Params8401HR
        param = Params8401HR(
                port            = 'badport', # 'COM1',
                preampDevice    = '8407-SE',            
                sampleRate      = 3000,            
                muxMode         = False,           
                preampGain      = (None, 10, 100, None),   
                ssGain          = (1, 1, 5, 5),   
                highPass        = (0, 0.5, 1, 10),   
                lowPass         = (100, 1000, 10000, 15000),   
                bias            = (0.6, -0.6, 1.0, -1.0),   
                dcMode          = ('VBIAS', 'AGND', 'VBIAS', 'AGND'),   
                checkForValidParams = True
            )
        return TestResult(False, "Params8401HR did not notice the invalid 'port' argument.")
    except Exception as e : 
        return TestResult(True, '')   
    

def Test3_BadPreampDev() : 
    """Tests if the Params8401HR object correctly raises an Exception when it recieves a bad 'preampDevice' argument. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    try : 
        # create instance of Params8401HR
        param = Params8401HR(
                port            = 'COM1',
                preampDevice    = 'uwu', # '8407-SE',
                sampleRate      = 3000,            
                muxMode         = False,           
                preampGain      = (None, 10, 100, None),   
                ssGain          = (1, 1, 5, 5),   
                highPass        = (0, 0.5, 1, 10),   
                lowPass         = (100, 1000, 10000, 15000),   
                bias            = (0.6, -0.6, 1.0, -1.0),   
                dcMode          = ('VBIAS', 'AGND', 'VBIAS', 'AGND'),   
                checkForValidParams = True
            )
        return TestResult(False, "Params8401HR did not notice the invalid 'preampDevice' argument.")
    except Exception as e : 
        return TestResult(True, '')  
    
     
def Test4_BadSampleRate() : 
    """Tests if the Params8401HR object correctly raises an Exception when it recieves a bad 'sampleRate' argument. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    try : 
        # create instance of Params8206HR
        param = Params8401HR(
                port            = 'COM1',
                preampDevice    = '8407-SE',            
                sampleRate      = 0, # 3000,            
                muxMode         = False,           
                preampGain      = (None, 10, 100, None),   
                ssGain          = (1, 1, 5, 5),   
                highPass        = (0, 0.5, 1, 10),   
                lowPass         = (100, 1000, 10000, 15000),   
                bias            = (0.6, -0.6, 1.0, -1.0),   
                dcMode          = ('VBIAS', 'AGND', 'VBIAS', 'AGND'),   
                checkForValidParams = True
            )
        return TestResult(False, "Params8401HR did not notice the invalid 'sampleRate' argument.")
    except Exception as e : 
        return TestResult(True, '')

def Test5_BadPreampGain() : 
    """Tests if the Params8401HR object correctly raises an Exception when it recieves a bad 'preampGain' argument. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    try : 
        # create instance of Params8206HR
        param = Params8401HR(
                port            = 'COM1',
                preampDevice    = '8407-SE',            
                sampleRate      = 0, # 3000,            
                muxMode         = False,           
                preampGain      = (-1, 1, -1000, 0), # (None, 10, 100, None),
                ssGain          = (1, 1, 5, 5),   
                highPass        = (0, 0.5, 1, 10),   
                lowPass         = (100, 1000, 10000, 15000),   
                bias            = (0.6, -0.6, 1.0, -1.0),   
                dcMode          = ('VBIAS', 'AGND', 'VBIAS', 'AGND'),   
                checkForValidParams = True
            )
        return TestResult(False, "Params8401HR did not notice the invalid 'preampGain' argument.")
    except Exception as e : 
        return TestResult(True, '')
    
def Test6_BadSsGain() : 
    """Tests if the Params8401HR object correctly raises an Exception when it recieves a bad 'ssGain' argument. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    try : 
        # create instance of Params8206HR
        param = Params8401HR(
                port            = 'COM1',
                preampDevice    = '8407-SE',            
                sampleRate      = 3000,            
                muxMode         = False,           
                preampGain      = (-1, 1, -1000, 0),   
                ssGain          = (0, -1, -5, 2), # (1, 1, 5, 5),   
                highPass        = (0, 0.5, 1, 10),   
                lowPass         = (100, 1000, 10000, 15000),   
                bias            = (0.6, -0.6, 1.0, -1.0),   
                dcMode          = ('VBIAS', 'AGND', 'VBIAS', 'AGND'),   
                checkForValidParams = True
            )
        return TestResult(False, "Params8401HR did not notice the invalid 'ssGain' argument.")
    except Exception as e : 
        return TestResult(True, '')
    
def Test7_BadHighPass() : 
    """Tests if the Params8401HR object correctly raises an Exception when it recieves a bad 'lowPass' argument. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    try : 
        # create instance of Params8206HR
        param = Params8401HR(
                port            = 'COM1',
                preampDevice    = '8407-SE',            
                sampleRate      = 0, # 3000,            
                muxMode         = False,           
                preampGain      = (-1, 1, -1000, 0),   
                ssGain          = (1, 1, 5, 5),   
                highPass        = (-1, 0.8, 2, 10.1), # (0, 0.5, 1, 10),   
                lowPass         = (100, 1000, 10000, 15000),   
                bias            = (0.6, -0.6, 1.0, -1.0),   
                dcMode          = ('VBIAS', 'AGND', 'VBIAS', 'AGND'),   
                checkForValidParams = True
            )
        return TestResult(False, "Params8401HR did not notice the invalid 'lowPass' argument.")
    except Exception as e : 
        return TestResult(True, '')
    
def Test8_BadLowPass() : 
    """Tests if the Params8401HR object correctly raises an Exception when it recieves a bad 'lowPass' argument. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    try : 
        # create instance of Params8206HR
        param = Params8401HR(
                port            = 'COM1',
                preampDevice    = '8407-SE',            
                sampleRate      = 3000,            
                muxMode         = False,           
                preampGain      = (-1, 1, -1000, 0),   
                ssGain          = (1, 1, 5, 5),   
                highPass        = (0, 0.5, 1, 10),   
                lowPass         = (0, 10, -10000, 16000), # (100, 1000, 10000, 15000), 
                bias            = (0.6, -0.6, 1.0, -1.0),   
                dcMode          = ('VBIAS', 'AGND', 'VBIAS', 'AGND'),   
                checkForValidParams = True
            )
        return TestResult(False, "Params8401HR did not notice the invalid 'lowPass' argument.")
    except Exception as e : 
        return TestResult(True, '')
    
def Test9_BadBias() : 
    """Tests if the Params8401HR object correctly raises an Exception when it recieves a bad 'bias' argument. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    try : 
        # create instance of Params8206HR
        param = Params8401HR(
                port            = 'COM1',
                preampDevice    = '8407-SE',            
                sampleRate      = 3000,            
                muxMode         = False,           
                preampGain      = (-1, 1, -1000, 0),   
                ssGain          = (1, 1, 5, 5),   
                highPass        = (0, 0.5, 1, 10),   
                lowPass         = (100, 1000, 10000, 15000),   
                bias            = (-2.05, -3, 2.05, 3), # (0.6, -0.6, 1.0, -1.0),   
                dcMode          = ('VBIAS', 'AGND', 'VBIAS', 'AGND'),   
                checkForValidParams = True
            )
        return TestResult(False, "Params8401HR did not notice the invalid 'bias' argument.")
    except Exception as e : 
        return TestResult(True, '')

def Test10_BadDcMode() : 
    """Tests if the Params8401HR object correctly raises an Exception when it recieves a bad 'dcMode' argument. 

    Returns:
        tuple[bool,str]: Bool is true when the test passes, false otherwise. \\
            The string is an optional message. 
    """
    try : 
        # create instance of Params8206HR
        param = Params8401HR(
                port            = 'COM1',
                preampDevice    = '8407-SE',            
                sampleRate      = 3000,            
                muxMode         = False,           
                preampGain      = (-1, 1, -1000, 0),   
                ssGain          = (1, 1, 5, 5),   
                highPass        = (0, 0.5, 1, 10),   
                lowPass         = (100, 1000, 10000, 15000),   
                bias            = (0.6, -0.6, 1.0, -1.0),   
                dcMode          = ('uh', 'oh', 'vas', 'agn'), # ('VBIAS', 'AGND', 'VBIAS', 'AGND'),   
                checkForValidParams = True
            )
        return TestResult(False, "Params8401HR did not notice the invalid 'dcMode' argument.")
    except Exception as e : 
        return TestResult(True, '')
# local imports
from Testing.T_Morelia.TestProtocol import RunningTests, TestResult
from Morelia.Packets import PacketBinary

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

# ---------------------------------------------------------------------------------------------------------
def RunTests(printTests: bool = True) -> tuple[int,int]: 
    """Run all tests on Morelia.Packets.PacketBinary

    Args:
        printTests (bool, optional): Make True to print the test results and messages. Defaults to True.
    
    Returns:
        tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
    """
    # collect all tests
    tests = {
        "1. Match Init:\t\t"        : MatchInit,
        "2. Unpack:\t\t"            : Unpack,
        "3. Translate:\t\t"         : Trans,
        "4. Static binary length:"  : StatLen,
        "4. Static binary data:\t"  : StatData,
        "5. Valid packet:\t"        : Valid,
    }
    return RunningTests.RunTests(tests, 'PacketBinary', printTests=printTests)
# ---------------------------------------------------------------------------------------------------------

def MatchInit() -> TestResult : 
    """Check to see if the PacketStandard object correctly stores values in its class instance variables. 

    Returns:
        TestResult: Result of the test.
    """
    # make Packet 
    raw = b'\x02000C00085F\x030123456782B\x03' # STX \x02 # CMD 000C = 12 # PLD 0008 = 8 # CSUM 5F # BINARY 012345678 # CS 2B # ETX \x03
    pkt = PacketBinary(raw)
    # check if in matches out 
    if(pkt.rawPacket     != raw) :          return TestResult(False, "PacketBinary does not contain correct raw bytes packet.")
    if(pkt.commandNumber != b'000C') :      return TestResult(False, "PacketBinary does not contain correct command number.")
    if(pkt.binaryLength  != b'0008') :      return TestResult(False, "PacketBinary does not contain correct binary length payload.")
    if(pkt.binaryData    != b'012345678') : return TestResult(False, "PacketBinary does not contain correct binary data.")
    return TestResult(True)

def Unpack() -> TestResult : 
    """Check to see if the class can unpack the raw bytes packet.

    Returns:
        TestResult: Result of the test.
    """
    # store expected 
    raw = b'\x02000C00085F\x030123456782B\x03' # STX \x02 # CMD 000C = 12 # PLD 0008 = 8 # CSUM 5F # BINARY 012345678 # CS 2B # ETX \x03
    expected = {'Command Number': b'000C', 'Binary Packet Length': b'0008', 'Binary Data': b'012345678'}
    # make Packet 
    pkt = PacketBinary(raw)
    if(expected != pkt.UnpackAll() ) : return TestResult(False, "Could not unpack the Packet.")
    return TestResult(True)
    
def Trans() -> TestResult : 
    """Check to see if the class can translate the raw bytes packet.

    Returns:
        TestResult: Result of the test.
    """
    # store expected 
    raw = b'\x02000C00085F\x030123456782B\x03' # STX \x02 # CMD 000C = 12 # PLD 0008 = 8 # CSUM 5F # BINARY 012345678 # CS 2B # ETX \x03
    expected = {'Command Number': 12, 'Binary Packet Length': 8, 'Binary Data': b'012345678'}
    # make Packet 
    pkt = PacketBinary(raw)
    # check 
    if(expected != pkt.TranslateAll() ) : return TestResult(False, "Could not translate the Packet.")
    return TestResult(True)
    
def StatLen() -> TestResult : 
    """Check of the class can extract the binary length from a bytes string. 

    Returns:
        TestResult: Result of the test.
    """
    if(PacketBinary.GetBinaryLength(b'\x02000C00085F\x030123456782B\x03') != b'0008' ) : return TestResult(False, "Could not extract binary length from raw data.")
    return TestResult(True)
    
def StatData() -> TestResult :
    """Check of the class can extract the binary data from a bytes string. 

    Returns:
        TestResult: Result of the test.
    """
    if(PacketBinary.GetBinaryData(b'\x02000C00085F\x030123456782B\x03') != b'012345678' ) : return TestResult(False, "Could not extract binary length from raw data.")
    return TestResult(True)
    
def Valid() -> TestResult : 
    """Checks if a binary packet is valid. 

    Returns:
        TestResult : Result of the test.
    """
    # good packet
    try : PacketBinary.CheckIfPacketIsValid(b'\x02000C00085F\x030123456782B\x03')
    except : return TestResult(False, "Flagged good packet as invalid.")
    # bad packet - no center ETX
    try : 
        PacketBinary.CheckIfPacketIsValid(b'\x02000C00085F0123456782B\x03')
        return TestResult(False, "Did not notice an invalid packet without center ETX.")
    except : pass
    # bad packet - too small 
    try : 
        PacketBinary.CheckIfPacketIsValid(b'\x02000C085F\x030123456782B\x03')
        return TestResult(False, "Did not notice an invalid packet that was missing bytes.")
    except : pass
    # finish
    return TestResult(True)
# local imports
from Testing.T_PodApi.TestProtocol import RunningTests, TestResult
from PodApi.Packets import PacketStandard
from PodApi.Commands import CommandSet

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"


# ---------------------------------------------------------------------------------------------------------
def RunTests(printTests: bool = True) -> tuple[int,int]: 
    """Run all tests on PodApi.Packets.Packet

    Args:
        printTests (bool, optional): Make True to print the test results and messages. Defaults to True.
    
    Returns:
        tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
    """
    # collect all tests
    tests = {
        "1. Match Init:\t\t"    : MatchInit,
        "2. Unpack:\t\t"        : Unpack,
        "3. Translate:\t\t"     : Trans,
    }
    return RunningTests.RunTests(tests, 'Packet', printTests=printTests)
# ---------------------------------------------------------------------------------------------------------

def MatchInit() -> TestResult : 
    raw = bytes(b'\x02000C01000003A8\x03') # STX \x02, COMMAND 000C, PAYLOAD 01000003, CSM A8, ETX \x03
    # make Packet 
    pkt = PacketStandard(raw, CommandSet())
    # check if in matches out 
    if(raw != pkt.rawPacket) : 
        return TestResult(False, "PacketStandard does not contain correct raw bytes packet.")
    elif(bytes(b'000C') != pkt.commandNumber) : 
        return TestResult(False, "PacketStandard has incorrect command number.")
    elif(bytes(b'01000003') != pkt.payload):
        return TestResult(False, "PacketStandard has incorrect packet.")
    else:
        return TestResult(True)
    

def Unpack() -> TestResult : 
    """Check to see if the class can unpack the command number from a raw bytes packet.

    Returns:
        TestResult: Result of the test.
    """
    # store expected 
    raw = bytes(b'\x02000C01000003A8\x03') # STX \x02, COMMAND 000C, PAYLOAD 01000003, CSM A8, ETX \x03
    expected = { 'Command Number' : bytes(b'000C'), 'Payload' : bytes(b'01000003') }
    # make Packet 
    pkt = PacketStandard(raw, CommandSet())
    if(expected != pkt.UnpackAll() ) : 
        return TestResult(False, "Could not unpack the Packet.")
    else : 
        return TestResult(True)
    
def Trans() -> TestResult : 
    """Check to see if the class can translate the command number from a raw bytes packet.

    Returns:
        TestResult: Result of the test.
    """
    # store expected 
    raw = bytes(b'\x02000C01000003A8\x03') # STX \x02, COMMAND 000C, PAYLOAD 01000003, CSM A8, ETX \x03
    expected = { 'Command Number' : 12, 'Payload': (1, 0, 3) }
    # make Packet 
    # pkt = PacketStandard(raw, CommandSet())
    pkt = PacketStandard(raw)
    # check 
    if(expected != pkt.TranslateAll() ) : 
        print(pkt.TranslateAll())
        return TestResult(False, "Could not translate the Packet.")
    else : 
        return TestResult(True)
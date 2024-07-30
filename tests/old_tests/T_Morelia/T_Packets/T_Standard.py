# local imports
from Testing.T_Morelia.TestProtocol import RunningTests, TestResult
from Morelia.Packets import PacketStandard
from Morelia.Commands import CommandSet
from Morelia.Devices import Pod8206HR

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

# ---------------------------------------------------------------------------------------------------------
def RunTests(printTests: bool = True) -> tuple[int,int]: 
    """Run all tests on Morelia.Packets.PacketStandard

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
        "4. Default payload:\t" : DefaultPld,
        "5. Custom payload:\t"  : CustomPld,
    }
    return RunningTests.RunTests(tests, 'PacketStandard', printTests=printTests)
# ---------------------------------------------------------------------------------------------------------

def MatchInit() -> TestResult : 
    """Check to see if the PacketStandard object correctly stores values in its class instance variables. 

    Returns:
        TestResult: Result of the test.
    """
    raw = bytes(b'\x02000C01000003A8\x03') # STX \x02, COMMAND 000C, PAYLOAD 01000003, CSM A8, ETX \x03
    # make Packet 
    pkt = PacketStandard(raw, CommandSet())
    # check if in matches out 
    if(raw != pkt.rawPacket) :                  return TestResult(False, "PacketStandard does not contain correct raw bytes packet.")
    if(bytes(b'000C') != pkt.commandNumber) :   return TestResult(False, "PacketStandard has incorrect command number.")
    if(bytes(b'01000003') != pkt.payload) :     return TestResult(False, "PacketStandard has incorrect packet.")
    return TestResult(True)

def Unpack() -> TestResult : 
    """Check to see if the class can unpack the raw bytes packet.

    Returns:
        TestResult: Result of the test.
    """
    # store expected 
    raw = bytes(b'\x02000C01000003A8\x03') # STX \x02, COMMAND 000C, PAYLOAD 01000003, CSM A8, ETX \x03
    expected = { 'Command Number' : bytes(b'000C'), 'Payload' : bytes(b'01000003') }
    # make Packet 
    pkt = PacketStandard(raw, CommandSet())
    if(expected != pkt.UnpackAll() ) : return TestResult(False, "Could not unpack the Packet.")
    return TestResult(True)
    
def Trans() -> TestResult : 
    """Check to see if the class can translate the raw bytes packet.

    Returns:
        TestResult: Result of the test.
    """
    # store expected 
    raw = bytes(b'\x02000C01000003A8\x03') # STX \x02, COMMAND 000C, PAYLOAD 01000003, CSM A8, ETX \x03
    expected = { 'Command Number' : 12, 'Payload': (1, 0, 3) }
    # make Packet 
    pkt = PacketStandard(raw, CommandSet())
    # check 
    if(expected != pkt.TranslateAll() ) : return TestResult(False, "Could not translate the Packet.")
    return TestResult(True)
    
def DefaultPld() -> TestResult :
    """Check to see if the PacketStandard can handle and interpret packets with and without payloads.

    Returns:
        TestResult: Result of the test.
    """
    # bytes packets
    rayNoP = bytes(b'\x0200023D\x03') # STX \x02, COMMAND 0002, CSM 3D, ETX \x03
    rawPld = bytes(b'\x02000C01000003A8\x03') # STX \x02, COMMAND 000C, PAYLOAD 01000003, CSM A8, ETX \x03
    # make Packet 
    pktNoP = PacketStandard(rayNoP, CommandSet())
    pktPld = PacketStandard(rawPld, CommandSet())
    # test
    if(pktNoP.payload != None) :            return TestResult(False, "Packet without payload stores a value as a payload.")
    if(pktPld.payload != b'01000003') :     return TestResult(False, "Packet with payload does not store a value as a payload.")
    if(pktPld.Payload() != (1, 0, 3) ) :    return TestResult(False, "Could not translate the given payload.")
    return TestResult(True)
    
def CustomPld() -> TestResult : 
    """Check to see if the PacketStandard can handle and interpret packets with and without custom payloads.

    Returns:
        TestResult: Result of the test.
    """
    # define custom payload function 
    def ExCustomPld(ttlByte: bytes) -> dict[str,int] : return Pod8206HR._TranslateTTLbyte_ASCII(ttlByte) 
    # expected packet
    raw = b'\x02006AF0B2\x03'
    pld = {'TTL1': 1, 'TTL2': 1, 'TTL3': 1, 'TTL4': 1}
    # make packet and set custom payload
    pkt = PacketStandard(raw, CommandSet())
    pkt.SetCustomPayload(ExCustomPld, (pkt.payload,))   
    # test
    if(not pkt.HasCustomPayload()) :    return TestResult(False, "Could not recognize it was given a custom payload function.")
    if(pld != pkt.Payload()) :          return TestResult(False, "Could not translate the custom payload.")
    return TestResult(True)

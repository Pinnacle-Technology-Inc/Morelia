# local imports
from Testing.T_Morelia.TestProtocol import RunningTests, TestResult
from Morelia.Packets import PacketBinary5

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

# ---------------------------------------------------------------------------------------------------------
def RunTests(printTests: bool = True) -> tuple[int,int]: 
    """Run all tests on Morelia.Packets.PacketBinary5

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
        "4. Static packets:\t"      : Stat,
    }
    return RunningTests.RunTests(tests, 'PacketBinary5', printTests=printTests)
# ---------------------------------------------------------------------------------------------------------

def MatchInit() -> TestResult : 
    """Check to see if the PacketStandard object correctly stores values in its class instance variables. 

    Returns:
        TestResult: Result of the test.
    """
    # make Packet 
    raw = b'\x0200B54\xff\x80\x14`\x02\xf7\xfer\x00"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0076\x03'
    pkt = PacketBinary5(raw)
    # check if in matches out 
    if(pkt.rawPacket     != raw) :          return TestResult(False, "PacketBinary does not contain correct raw bytes packet.")
    if(pkt.packetNumber  != b'4') :         return TestResult(False, "PacketBinary does not contain correct command number.")
    if(pkt.status        != b'\xff') :      return TestResult(False, "PacketBinary does not contain correct status.")
    if(pkt.channels      != b'\x80\x14`\x02\xf7\xfer\x00"') : return TestResult(False, "PacketBinary does not contain correct channels.")
    if(pkt.aEXT0         != b'\x00\x00') :  return TestResult(False, "PacketBinary does not contain correct aEXT0.")
    if(pkt.aEXT1         != b'\x00\x00') :  return TestResult(False, "PacketBinary does not contain correct aEXT1.")
    if(pkt.aTTL1         != b'\x00\x00') :  return TestResult(False, "PacketBinary does not contain correct aTTL1.")
    if(pkt.aTTL2         != b'\x00\x00') :  return TestResult(False, "PacketBinary does not contain correct aTTL2.")
    if(pkt.aTTL3         != b'\x00\x00') :  return TestResult(False, "PacketBinary does not contain correct aTTL3.")
    if(pkt.aTTL4         != b'\x00\x00') :  return TestResult(False, "PacketBinary does not contain correct aTTL4.")
    return TestResult(True)

def Unpack() -> TestResult : 
    """Check to see if the class can unpack the raw bytes packet.

    Returns:
        TestResult: Result of the test.
    """
    # store expected 
    raw = b'\x0200B54\xff\x80\x14`\x02\xf7\xfer\x00"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0076\x03'
    expected = {'Command Number': b'00B5', 'Packet #': b'4', 'Status': b'\xff', 'Channels': b'\x80\x14`\x02\xf7\xfer\x00"', 'Analog EXT0': b'\x00\x00', 'Analog EXT1': b'\x00\x00', 'Analog TTL1': b'\x00\x00', 'Analog TTL2': b'\x00\x00', 'Analog TTL3': b'\x00\x00', 'Analog TTL4': b'\x00\x00'}
    # make Packet 
    pkt = PacketBinary5(raw)
    if(expected != pkt.UnpackAll() ) : return TestResult(False, "Could not unpack the packet.")
    return TestResult(True)
    
def Trans() -> TestResult : 
    """Check to see if the class can translate the raw bytes packet.

    Returns:
        TestResult: Result of the test.
    """
    # store expected 
    raw = b'\x0200B54\xff\x80\x14`\x02\xf7\xfer\x00"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0076\x03'
    expected = {'Command Number': b'00B5', 'Packet #': 52, 'Status': 255, 'Analog EXT0': 0.0, 'Analog EXT1': 0.0, 'Analog TTL1': 0.0, 'Analog TTL2': 0.0, 'Analog TTL3': 0.0, 'Analog TTL4': 0.0}
    # make Packet 
    pkt = PacketBinary5(raw)    
    # check 
    if(expected != pkt.TranslateAll() ) : return TestResult(False, "Could not translate the packet.")
    return TestResult(True)
    
def Stat() -> TestResult :
    """Check to see if the static Get_() functions can extract the proper values from a bytes packet. 

    Returns:
        TestResult: Result of the test.
    """
    raw = b'\x0200B54\xff\x80\x14`\x02\xf7\xfer\x00"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0076\x03'
    if(PacketBinary5.GetPacketNumber (raw) != b'4') :           return TestResult(False, "Could not extract packet number from bytes.")
    if(PacketBinary5.GetStatus       (raw) != b'\xff') :        return TestResult(False, "Could not extract TTL from bytes.")
    if(PacketBinary5.GetChannels     (raw) != b'\x80\x14`\x02\xf7\xfer\x00"') : return TestResult(False, "Could not extract CH0 from bytes.")
    if(PacketBinary5.GetAnalogEXT (0, raw) != b'\x00\x00') :    return TestResult(False, "Could not extract analog EXT0 from bytes.")
    if(PacketBinary5.GetAnalogEXT (1, raw) != b'\x00\x00') :    return TestResult(False, "Could not extract analog EXT1 from bytes.")
    if(PacketBinary5.GetAnalogTTL (1, raw) != b'\x00\x00') :    return TestResult(False, "Could not extract analog TTL1 from bytes.")
    if(PacketBinary5.GetAnalogTTL (2, raw) != b'\x00\x00') :    return TestResult(False, "Could not extract analog TTL2 from bytes.")
    if(PacketBinary5.GetAnalogTTL (3, raw) != b'\x00\x00') :    return TestResult(False, "Could not extract analog TTL3 from bytes.")
    if(PacketBinary5.GetAnalogTTL (4, raw) != b'\x00\x00') :    return TestResult(False, "Could not extract analog TTL4 from bytes.")
    return TestResult(True)

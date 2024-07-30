# local imports
from Testing.T_Morelia.TestProtocol import RunningTests, TestResult
from Morelia.Packets import PacketBinary4

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

# ---------------------------------------------------------------------------------------------------------
def RunTests(printTests: bool = True) -> tuple[int,int]: 
    """Run all tests on Morelia.Packets.PacketBinary4

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
        "5. TTL bytes:\t\t"         : TtlBytes,
        "6. Voltage:\t\t"           : Voltage,
    }
    return RunningTests.RunTests(tests, 'PacketBinary4', printTests=printTests)
# ---------------------------------------------------------------------------------------------------------

def MatchInit() -> TestResult : 
    """Check to see if the PacketStandard object correctly stores values in its class instance variables. 

    Returns:
        TestResult: Result of the test.
    """
    # make Packet 
    raw = b'\x0200B4\xfc\xf0\xa0\x7f\xf0\x7f\xf4\x7f3C\x03' # b'00B4' b'\xfc' b'\xf0' b'\xa0\x7f' b'\xf0\x7f' b'\xf4\x7f'
    pkt = PacketBinary4(raw,10)
    # check if in matches out 
    if(pkt.rawPacket     != raw) :          return TestResult(False, "PacketBinary does not contain correct raw bytes packet.")
    if(pkt.commandNumber != b'00B4') :      return TestResult(False, "PacketBinary does not contain correct command number.")
    if(pkt.packetNumber  != b'\xfc') :      return TestResult(False, "PacketBinary does not contain correct packet number.")
    if(pkt.ttl           != b'\xf0') :      return TestResult(False, "PacketBinary does not contain correct TTL.")
    if(pkt.ch0           != b'\xa0\x7f') :  return TestResult(False, "PacketBinary does not contain correct ch0.")
    if(pkt.ch1           != b'\xf0\x7f') :  return TestResult(False, "PacketBinary does not contain correct ch1.")
    if(pkt.ch2           != b'\xf4\x7f') :  return TestResult(False, "PacketBinary does not contain correct ch2.")
    return TestResult(True)

def Unpack() -> TestResult : 
    """Check to see if the class can unpack the raw bytes packet.

    Returns:
        TestResult: Result of the test.
    """
    # store expected 
    raw = b'\x0200B4\xfc\xf0\xa0\x7f\xf0\x7f\xf4\x7f3C\x03' # b'00B4' b'\xfc' b'\xf0' b'\xa0\x7f' b'\xf0\x7f' b'\xf4\x7f'
    expected = {'Command Number': b'00B4', 'Packet #': b'\xfc', 'TTL': b'\xf0', 'Ch0': b'\xa0\x7f', 'Ch1': b'\xf0\x7f', 'Ch2': b'\xf4\x7f'}
    # make Packet 
    pkt = PacketBinary4(raw,10)
    if(expected != pkt.UnpackAll() ) : return TestResult(False, "Could not unpack the Packet.")
    return TestResult(True)
    
def Trans() -> TestResult : 
    """Check to see if the class can translate the raw bytes packet.

    Returns:
        TestResult: Result of the test.
    """
    # store expected 
    raw = b'\x0200B4\xfc\xf0\xa0\x7f\xf0\x7f\xf4\x7f3C\x03' # b'00B4' b'\xfc' b'\xf0' b'\xa0\x7f' b'\xf0\x7f' b'\xf4\x7f'
    expected = {'Command Number': 180, 'Packet #': 252, 'TTL': {'TTL1': 1, 'TTL2': 1, 'TTL3': 1, 'TTL4': 1}, 'Ch0': -1.1868418066736771e-05, 'Ch1': -1.9262877490514255e-06, 'Ch2': -1.4291812331671582e-06}
    # make Packet 
    pkt = PacketBinary4(raw,10)
    # check 
    if(expected != pkt.TranslateAll() ) : return TestResult(False, "Could not translate the Packet.")
    return TestResult(True)
    
def Stat() -> TestResult :
    """Check to see if the static Get_() functions can extract the proper values from a bytes packet. 

    Returns:
        TestResult: Result of the test.
    """
    raw = b'\x0200B4\xfc\xf0\xa0\x7f\xf0\x7f\xf4\x7f3C\x03' # b'00B4' b'\xfc' b'\xf0' b'\xa0\x7f' b'\xf0\x7f' b'\xf4\x7f'
    if(PacketBinary4.GetPacketNumber(raw) != b'\xfc') : return TestResult(False, "Could not extract packet number from bytes.")
    if(PacketBinary4.GetTTL(raw) != b'\xf0') :          return TestResult(False, "Could not extract TTL from bytes.")
    if(PacketBinary4.GetCh(0, raw) != b'\xa0\x7f') :    return TestResult(False, "Could not extract CH0 from bytes.")
    if(PacketBinary4.GetCh(1, raw) != b'\xf0\x7f') :    return TestResult(False, "Could not extract CH1 from bytes.")
    if(PacketBinary4.GetCh(2, raw) != b'\xf4\x7f') :    return TestResult(False, "Could not extract CH2 from bytes.")
    return TestResult(True)
    
def TtlBytes() -> TestResult :
    """Check to see if the class can convert bytes into its different TTL components. 

    Returns:
        TestResult: Result of the test.
    """
    if(PacketBinary4.TranslateBinaryTTLbyte(b'\xf0') != {'TTL1': 1, 'TTL2': 1, 'TTL3': 1, 'TTL4': 1}) : 
        return TestResult(False, "Could not translate TTL bytes.")
    return TestResult(True)
    
def Voltage()  -> TestResult :
    """Check to see if the class can convert a bytes string into a voltage float.

    Returns:
        TestResult: Result of the test.
    """
    if(PacketBinary4.BinaryBytesToVoltage(b'\xa0\x7f', 10) != -1.1868418066736771e-05) : 
        return TestResult(False, "Could not convert bytes into a voltage.")
    return TestResult(True)
    
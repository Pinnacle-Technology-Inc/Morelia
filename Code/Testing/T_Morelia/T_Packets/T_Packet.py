# local imports
from Morelia.Packets import Packet
from Morelia.Commands import CommandSet
from Testing.T_Morelia.TestProtocol import RunningTests, TestResult

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

# ---------------------------------------------------------------------------------------------------------
def RunTests(printTests: bool = True) -> tuple[int,int]: 
    """Run all tests on Morelia.Packets.Packet

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
        "4. Command number:\t"  : Command,
        "5. Static cmd num:\t"  : GetCmd,
        "6. Pkt validation:\t"  : ValidPkt,
        "7. Has Commands:\t"    : HasCommands,
        "8. Has cmd num:\t\t"   : HasCmdNum,
        "9. Twos complement:\t" : TwosC,
        "10. Int to ASCII bytes\t"  : IntAscii,
        "11. ASCII bytes to Int:\t" : AsciiInt,
        "12. Binary bytes to Int:"  : BinaryInt,
        "13. ASCII split:\t"  : AsciiSplit,
        "14. Binary split:\t" : BinarySplit,
    }
    return RunningTests.RunTests(tests, 'Packet', printTests=printTests)
# ---------------------------------------------------------------------------------------------------------

def MatchInit() -> TestResult : 
    """Check to see if the Packet object correctly stores values in its class instance variables. 

    Returns:
        TestResult: Result of the test.
    """
    # store expected 
    cmd = bytes(b'000C')
    raw = bytes(b'\x02000C01000003A8\x03') # STX \x02, COMMAND 000C, PAYLOAD 01000003, CSM A8, ETX \x03
    # make Packet 
    pkt = Packet(raw)
    # check if in matches out 
    if(raw != pkt.rawPacket) : 
        return TestResult(False, "Packet does not contain correct raw bytes packet.")
    elif(cmd != pkt.commandNumber) : 
        return TestResult(False, "Packet has incorrect command number.")
    else:
        return TestResult(True)
    
def Unpack() -> TestResult : 
    """Check to see if the class can unpack the command number from a raw bytes packet.

    Returns:
        TestResult: Result of the test.
    """
    # store expected 
    raw = bytes(b'\x02000C01000003A8\x03') # STX \x02, COMMAND 000C, PAYLOAD 01000003, CSM A8, ETX \x03
    expected = { 'Command Number' : bytes(b'000C') }
    # make Packet 
    pkt = Packet(raw)
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
    expected = { 'Command Number' : 12 }
    # make Packet 
    pkt = Packet(raw)
    # check 
    if(expected != pkt.TranslateAll() ) : 
        return TestResult(False, "Could not translate the Packet.")
    else : 
        return TestResult(True)
    
def Command() -> TestResult : 
    """Check to see if the class can extract the command number. 

    Returns:
        TestResult: Result of the test.
    """
    # store expected 
    raw = bytes(b'\x02000C01000003A8\x03') # STX \x02, COMMAND 000C, PAYLOAD 01000003, CSM A8, ETX \x03
    expected = 12
    # make Packet 
    pkt = Packet(raw)
    # check
    if(expected != pkt.CommandNumber()) :
        return TestResult(False, "Could not get the integer command number from the Packet.")
    else : 
        return TestResult(True)
        
def GetCmd() -> TestResult : 
    """Check to see if the static class can get the command number from a bytes packet. 

    Returns:
        TestResult: Result of the test.
    """
    # store expected 
    raw = bytes(b'\x02000C01000003A8\x03') # STX \x02, COMMAND 000C, PAYLOAD 01000003, CSM A8, ETX \x03
    # get command 
    if( bytes(b'000C') != Packet.GetCommandNumber(raw) ) : 
        return TestResult(False, "Could not extract the command number from the bytes packet.")
    else : 
        return TestResult(True)
    
def ValidPkt() -> TestResult :
    """Check to see if the class can correctly determine if a bytes packet is correctly formatted.

    Returns:
        TestResult: Result of the test.
    """
    # good packet
    try : 
        Packet.CheckIfPacketIsValid( bytes(b'\x02000C01000003A8\x03') )             
    except : 
        return TestResult(False, "Flagged a correct bytes packet as invalid.")
    # bad packet without STX
    try : 
        Packet.CheckIfPacketIsValid( bytes(b'000C01000003A8\x03') )   
        return TestResult(False, "Did not notice that bytes packet had no STX.")
    except : pass
    # bad packet without ETX    
    try : 
        Packet.CheckIfPacketIsValid( bytes(b'000C01000003A8\x03') )
        return TestResult(False, "Did not notice that bytes packet had no ETX.")
    except : pass
    # finish
    return TestResult(True)
    
def HasCommands() -> TestResult :
    """Check to see if a class can store an optional CommandSet.

    Returns:
        TestResult: Result of the test.
    """
    raw = bytes(b'\x02000C01000003A8\x03') # STX \x02, COMMAND 000C, PAYLOAD 01000003, CSM A8, ETX \x03
    # make Packets with and without commands 
    pktYes = Packet(raw, CommandSet())
    pktNo = Packet(raw)
    # check
    if(not pktYes.HasCommands()) : 
        return TestResult(False, "Packet is missing a command set.")
    elif(pktNo.HasCommands()) : 
        return TestResult(False, "Packet without a command set thinks it does.")
    else :
        return TestResult(True)
    
def HasCmdNum() -> TestResult : 
    """Check to see if the class stores a command number from a packet when it has one. 

    Returns:
        TestResult: Result of the test.
    """
    # make Packets with and without commands 
    pktYes = Packet(bytes(b'\x02000C01000003A8\x03'))
    pktNo = Packet(bytes(b'\x020C\x03'))
    # check
    if(not pktYes.HasCommandNumber()) : 
        return TestResult(False, "Packet is missing a command number.")
    elif(pktNo.HasCommandNumber()) : 
        return TestResult(False, "Packet without a command number thinks it does.")
    else :
        return TestResult(True)
    
def TwosC() -> TestResult : 
    """Calculate the twos complement of a negative integer.

    Returns:
        TestResult: Result of the test.
    """
    # start  -> 101 = uint 5
    # invert -> 010
    # add 1  -> 011 = uint 3
    if(-0b011 != Packet.TwosComplement(val=0b101, nbits=3)) : 
        return TestResult(False, "Failed to compute 2C of 5 == -3.")
    return TestResult(True)
    
def IntAscii() -> TestResult : 
    """Convert an integer into ASCII encoded bytes. 

    Returns:
        TestResult: _description_
    """
    #             255   -- dec
    #           F   F   -- hex char
    #         x46 x46   -- ASCII code for 'F' (use table ie. https://www.asciitable.com/ )
    # x30 x30 x46 x46   -- prepend zeros 
    #         b'00FF'   -- bytes
    if(bytes(b'00FF') != Packet.IntToAsciiBytes(value=255, numChars=4)) :
        return TestResult(False, "Failed to encode 255 (xFF) to bytes.")
    return TestResult(True)    
    
def AsciiInt() -> TestResult :
    """Decode ASCII encoded bytes into an integer.

    Returns:
        TestResult: Result of the test.
    """
    #         b'00FF'   -- bytes
    # x30 x30 x46 x46   -- to ASCII code
    #   0   0   F   F   -- to hex character
    #             255   -- to decimal number
    if( 255 != Packet.AsciiBytesToInt(bytes(b'00FF')) ) : 
        return TestResult(False, "Failed to decode bytes as 255 (xFF).")
    return TestResult(True)

def BinaryInt() -> TestResult : 
    """Convert a binary encoded bytes string into an integer. 

    Returns:
        TestResult: Result of the test.
    """
    # bytes -> 1
    # to ASCII code -> 49 dec
    if(49 != Packet.BinaryBytesToInt(b'1')) : 
        return TestResult(False, "Could not convert ")
    return TestResult(True)
    
def AsciiSplit() -> TestResult :
    """Get the ASCII bytes for certaian range of bits. 

    Returns:
        TestResult: Result of the test.
    """
    #   b'EF' -> 1110 1111
    #   1110 1111
    # & 0001 1111 == keep 5 bits
    # = 0000 1111
    #   0000 1111 >> 1 = shift left to cut bottom 1
    # = 0000 0111 == 7 dec
    if(7 != Packet.ASCIIbytesToInt_Split(msg=b'EF', keepTopBits=5, cutBottomBits=1)) : 
        return TestResult(False, "Could not retrieve correct 4 bits from message.")
    return TestResult(True)

def BinarySplit() -> TestResult : 
    """Get the binary bytes for certaian range of bits.

    Returns:
        TestResult: Result of the test.
    """
    # b'1' --> to ASCII code x31 --> 00110001
    #   0011 0001
    #   0001 1111 == keep 5 bits
    # = 0001 0001
    #   0001 0001 >> 1 = shift left to cut bottom 1
    # = 0000 1000 == 8 dec
    if(8 != Packet.BinaryBytesToInt_Split(msg=b'1', keepTopBits=5, cutBottomBits=1)) : 
        return TestResult(False, "Could not retrieve correct 4 bits from message.")
    return TestResult(True)
    
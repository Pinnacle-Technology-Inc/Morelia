# local imports
from Testing.T_Morelia.TestProtocol import RunningTests, TestResult
from Morelia.Devices import Pod8206HR
from Morelia.packet import ControlPacket, PodPacket
from Morelia.packet.data import DataPacket8206HR

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class T_Pod8206HR : 
    
    def __init__(self, port: str = '', preampGain: int = 10, forbidden: list[str] = [] ) -> None :
        # get port from user 
        if(port == '') : 
            print('~~~~~~~~~~ 8206HR ~~~~~~~~~~')
            self.port: str = Pod8206HR.ChoosePort(forbidden)
            print('~~~~~~~~~~~~~~~~~~~~~~~~~~~~')
        else : 
            self.port = port
        # create pod device object 
        self.pod: Pod8206HR = Pod8206HR(self.port, preampGain)

    # ---------------------------------------------------------------------------------------------------------
    def RunTests(self, printTests: bool = True) -> tuple[int,int]: 
        """Run all tests on Morelia.Packets.ControlPacket

        Args:
            printTests (bool, optional): Make True to print the test results and messages. Defaults to True.
        
        Returns:
            tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
        """

        # collect all tests
        tests = {
            "1. Ping:\t\t"          : self.Ping,
            "2. Type:\t\t"          : self.Type,
            "3. Firmware:\t\t"      : self.FirmVer,
            "4. Sample rate:\t\t"   : self.SampRat,
            "5. Low pass:\t\t"      : self.LowP,
            "6. TTL:\t\t\t"         : self.Ttl,
            "7. Filter Config:\t"   : self.FiltConf,
            "8. Stream:\t\t"        : self.Stream,
        }
        return RunningTests.RunTests(tests, 'Pod8206HR', printTests=printTests)
    # ---------------------------------------------------------------------------------------------------------

    def Ping(self) -> TestResult : 
        # call command
        r = self.pod.WriteRead('PING')
        # check 
        if(  not isinstance(r,PodPacket)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,ControlPacket)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number  != 2    ) :         return TestResult(False, 'Packet has an incorrect command number.')
        elif(r. payload != tuple() ) :         return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good
        return TestResult(True)

    def Type(self) -> TestResult : 
        # call command
        r = self.pod.WriteRead('TYPE')
        # check 
        if(  not isinstance(r,PodPacket)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,ControlPacket)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number  != 8     ) :        return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.payload        != (48,) ) :        return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good
        return TestResult(True)
        
    def FirmVer(self) -> TestResult : 
        # call command
        r = self.pod.WriteRead('FIRMWARE VERSION')
        # check 
        if(  not isinstance(r,PodPacket)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,ControlPacket)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number  != 12     ) :       return TestResult(False, 'Packet has an incorrect command number.')
        elif(not isinstance(r.payload, tuple) 
             or len(r.payload) != 3 ) :           return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good
        return TestResult(True)
    
    def SampRat(self) -> TestResult : 
        sampleRate: int = 1000
        # set
        r = self.pod.WriteRead('SET SAMPLE RATE', sampleRate)
        # check 
        if(  not isinstance(r,PodPacket)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,ControlPacket)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number  != 101     ) :      return TestResult(False, 'Packet has an incorrect command number.')
        elif(r. payload != tuple() ) :         return TestResult(False, 'Packet has incorrect payload.')
        # get
        r = self.pod.WriteRead('GET SAMPLE RATE')
        # check 
        if(  not isinstance(r,PodPacket)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,ControlPacket)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number != 100     ) :       return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.payload       != (sampleRate,) ) : return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True)
        
    def LowP(self) -> TestResult : 
        channel: int = 0
        lowPass: int = 40
        # set
        r = self.pod.WriteRead('SET LOWPASS', (channel,lowPass))
        # check 
        if(  not isinstance(r,PodPacket)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,ControlPacket)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number  != 103     ) :      return TestResult(False, 'Packet has an incorrect command number.')
        elif(r. payload != tuple() ) :         return TestResult(False, 'Packet has incorrect payload.')
        # get
        r = self.pod.WriteRead('GET LOWPASS', channel)
        # check 
        if(  not isinstance(r,PodPacket)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,ControlPacket)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number != 102     ) :       return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.payload       != (lowPass,) ) :    return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True)
    
    def Ttl(self) -> TestResult : 
        ttl: dict[str,int] = { 'TTL1' : 0, 'TTL2' : 1, 'TTL3' : 0, 'TTL4' : 1, }
        # set  
        r = self.pod.WriteRead('SET TTL OUT', (0, ttl['TTL1']) )
        r = self.pod.WriteRead('SET TTL OUT', (1, ttl['TTL2']) )
        r = self.pod.WriteRead('SET TTL OUT', (2, ttl['TTL3']) )
        r = self.pod.WriteRead('SET TTL OUT', (3, ttl['TTL4']) )
        # check last
        if(  not isinstance(r,PodPacket)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,ControlPacket)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number  != 104     ) :      return TestResult(False, 'Packet has an incorrect command number.')
        elif(r. payload != tuple() ) :         return TestResult(False, 'Packet has incorrect payload.')
        # get 
        r = self.pod.WriteRead('GET TTL PORT')
        # check 
        if(  not isinstance(r,PodPacket)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,ControlPacket)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number != 106     ) :       return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.payload       != (ttl,) ) :           return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True)
    
    def FiltConf(self) -> TestResult : 
        # call command
        r = self.pod.WriteRead('GET FILTER CONFIG') # 0=SL, 1=SE (Both 40/40/100Hz lowpass), 2 = SE3 (40/40/40Hz lowpas).
        # check 
        if(  not isinstance(r,PodPacket)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,ControlPacket)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number  != 107     ) :      return TestResult(False, 'Packet has an incorrect command number.')
        elif(not isinstance(r.payload, tuple)) :  return TestResult(False, 'Packet is missing a payload.')
        elif(len(r.payload) > 1) :                return TestResult(False, 'Packet is incorrect size.')
        elif(r.payload[0] not in [0,1,2]) :  return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True)
    
    def Stream(self) -> TestResult :
        # call command
        r = self.pod.WriteRead('STREAM', 1) 
        # check 
        if(  not isinstance(r,PodPacket)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,ControlPacket)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number  != 6     ) :        return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.payload        != (1,) ) :         return TestResult(False, 'Packet has incorrect payload.')
        # stop streaming 
        self.pod.WritePacket('STREAM', 0) 
        # next read packet should be stream data
        r = self.pod.ReadPODpacket()
        if(  not isinstance(r,PodPacket)) :            return TestResult(False, 'Stream did not return a packet')
        elif(not isinstance(r,DataPacket8206HR)) :     return TestResult(False, 'Command did not return a binary4 packet')
        # clean out data 
        self.pod.FlushPort()
        # otherwise good 
        return TestResult(True)

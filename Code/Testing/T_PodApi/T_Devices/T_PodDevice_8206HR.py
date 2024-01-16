# local imports
from Testing.T_PodApi.TestProtocol import RunningTests, TestResult
from PodApi.Devices import Pod8206HR
from PodApi.Packets import Packet, PacketStandard

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class T_Pod8206HR : 
    
    def __init__(self, port: str = '', preampGain: int = 10 ) -> None :
        # get port from user 
        if(port == '') : useport: str = Pod8206HR.ChoosePort()
        else :           useport = port
        # create pod device object 
        self.pod: Pod8206HR = Pod8206HR(useport, preampGain)

    # ---------------------------------------------------------------------------------------------------------
    def RunTests(self, printTests: bool = True) -> tuple[int,int]: 
        """Run all tests on PodApi.Packets.PacketStandard

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
            "7. Filter Config:\t\t" : self.FiltConf,
        }
        return RunningTests.RunTests(tests, 'Pod8206HR', printTests=printTests)
    # ---------------------------------------------------------------------------------------------------------

    def Ping(self) -> TestResult : 
        # call command
        r = self.pod.WriteRead('PING')
        # check 
        if(  not isinstance(r,Packet)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 2    ) :         return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()        != None ) :         return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good
        return TestResult(True)

    def Type(self) -> TestResult : 
        # call command
        r = self.pod.WriteRead('TYPE')
        # check 
        if(  not isinstance(r,Packet)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 8     ) :        return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()        != (48,) ) :        return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good
        return TestResult(True)
        
    def FirmVer(self) -> TestResult : 
        # call command
        r = self.pod.WriteRead('FIRMWARE VERSION')
        # check 
        if(  not isinstance(r,Packet)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 12     ) :       return TestResult(False, 'Packet has an incorrect command number.')
        elif(not isinstance(r.Payload(), tuple) 
             or len(r.Payload()) != 3 ) :           return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good
        return TestResult(True)
    
    def SampRat(self) -> TestResult : 
        sampleRate: int = 1000
        # set
        r = self.pod.WriteRead('SET SAMPLE RATE', sampleRate)
        # check 
        if(  not isinstance(r,Packet)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 101     ) :      return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()        != None ) :         return TestResult(False, 'Packet has incorrect payload.')
        # get
        r = self.pod.WriteRead('GET SAMPLE RATE')
        # check 
        if(  not isinstance(r,Packet)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber() != 100     ) :       return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()       != (sampleRate,) ) : return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True)
        
    def LowP(self) -> TestResult : 
        channel: int = 0
        lowPass: int = 40
        # set
        r = self.pod.WriteRead('SET LOWPASS', (channel,lowPass))
        # check 
        if(  not isinstance(r,Packet)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 103     ) :      return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()        != None ) :         return TestResult(False, 'Packet has incorrect payload.')
        # get
        r = self.pod.WriteRead('GET LOWPASS', channel)
        # check 
        if(  not isinstance(r,Packet)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber() != 102     ) :       return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()       != (lowPass,) ) :    return TestResult(False, 'Packet has incorrect payload.')
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
        if(  not isinstance(r,Packet)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 104     ) :      return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()        != None ) :         return TestResult(False, 'Packet has incorrect payload.')
        # get 
        r = self.pod.WriteRead('GET TTL PORT')
        # check 
        if(  not isinstance(r,Packet)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber() != 106     ) :       return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()       != ttl ) :           return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True)
    
    def FiltConf(self) -> TestResult : 
        
        # otherwise good 
        return TestResult(True)
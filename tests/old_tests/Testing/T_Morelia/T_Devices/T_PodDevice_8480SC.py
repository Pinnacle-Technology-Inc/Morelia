# local imports
from Testing.T_Morelia.TestProtocol import RunningTests, TestResult
from Morelia.Devices import Pod8480SC
from Morelia.Packets import Packet, PacketStandard, PacketBinary4

# authorship
__author__      = "Sree Kondi"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Sree Kondi", "Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"


class T_Pod8480SC : 
    
    def __init__(self, port: str = '', forbidden: list[str] = [] ) -> None :
        # get port from user 
        if(port == '') : 
            print('~~~~~~~~~~ 8480SC ~~~~~~~~~~')
            self.port: str = Pod8480SC.ChoosePort(forbidden)
            print('~~~~~~~~~~~~~~~~~~~~~~~~~~~~')
        else :
            self.port = port
        # create pod device object 
        self.pod: Pod8480SC = Pod8480SC(self.port)

        # ---------------------------------------------------------------------------------------------------------
    def RunTests(self, printTests: bool = True) -> tuple[int,int]: 
            """Run all tests on Morelia.Packets.PacketStandard

            Args:
                printTests (bool, optional): Make True to print the test results and messages. Defaults to True.
            
            Returns:
                tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
            """

            # collect all tests
            tests = {
                "1. Ping:\t\t"              : self.Ping,
                "2. Type:\t\t"              : self.Type,
                "3. Firmware:\t\t"          : self.FirmVer,
                "4. Led Current:\t\t"       : self.LedCurrent,
                "5. Estim Current:\t"       : self.EstimCurrent,
                "5. PreAmp:\t\t"            : self.PreAmp,
                "6. TtlPullups:\t\t"        : self.TtlPullups,
                "7. SynConfig:\t\t"         : self.SynConfig,
                "8. Stimulus:\t\t"          : self.Stimulus,      
                "9. Run Stimulus:\t"        : self.Run_Stimulus, 
                "10. EventTtl:\t\t"         : self.Event_Ttl,       
            }
            return RunningTests.RunTests(tests, 'Pod8480SC', printTests=printTests)

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
        if(  not isinstance(r,Packet)) :                return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :        return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 8     ) :            return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()        != (0x32,) ) :          return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good
        return TestResult(True)
    
    def FirmVer(self) -> TestResult : 
        # call command
        r = self.pod.WriteRead('FIRMWARE VERSION')
        # check 
        if(  not isinstance(r,Packet)) :                return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :        return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 12     ) :           return TestResult(False, 'Packet has an incorrect command number.')
        elif(not isinstance(r.Payload(), tuple) 
             or len(r.Payload()) != 3 ) :               return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good
        return TestResult(True)
    

    def LedCurrent(self) -> TestResult : 
        ledCurr = [22,23]
        expected_payload = (ledCurr[0], ledCurr[1])
        # set
        r = self.pod.WriteRead('SET LED CURRENT', (0, ledCurr[0]))
        r = self.pod.WriteRead('SET LED CURRENT', (1, ledCurr[1]))
        # check 
        if(  not isinstance(r,Packet)) :                return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :        return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 117     ) :          return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()        != None ) :             return TestResult(False, 'Packet has incorrect payload.')
        # get
        r = self.pod.WriteRead('GET LED CURRENT')
        # check 
        if(  not isinstance(r,Packet)) :                return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :        return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber() != 116     ) :           return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()     != (expected_payload) ) :  return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True)
    
    
    def EstimCurrent(self) -> TestResult : 
        estimCurr = [22,23]
        expected_payload = (estimCurr[0], estimCurr[1])
        # set
        r = self.pod.WriteRead('SET ESTIM CURRENT', (0, estimCurr[0]))
        r = self.pod.WriteRead('SET ESTIM CURRENT', (1, estimCurr[1]))
        # check 
        if(  not isinstance(r,Packet)) :                return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :        return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 119     ) :          return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()        != None ) :             return TestResult(False, 'Packet has incorrect payload.')
        # get
        r = self.pod.WriteRead('GET ESTIM CURRENT')
        # check 
        if(  not isinstance(r,Packet)) :                return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :        return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber() != 118     ) :           return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()  != (expected_payload)) :      return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True)
    

    def PreAmp(self) -> TestResult : 
        preamp = 0
        # set
        r = self.pod.WriteRead('SET PREAMP TYPE', preamp)
        # check 
        if(  not isinstance(r,Packet)) :                return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :        return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 125     ) :          return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()        != None ) :             return TestResult(False, 'Packet has incorrect payload.')
        # get
        r = self.pod.WriteRead('GET PREAMP TYPE')
        # check 
        if(not isinstance(r,PacketStandard)) :          return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber() != 124     ) :           return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()       != (preamp,) ) :         return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True)
    
    
    def TtlPullups(self) -> TestResult : 
        ttlpullups = 1
        # set
        r = self.pod.WriteRead('SET TTL PULLUPS', ttlpullups)
        # check 
        if(  not isinstance(r,Packet)) :                return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :        return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 111     ) :          return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()        != None ) :             return TestResult(False, 'Packet has incorrect payload.')
        # get
        r = self.pod.WriteRead('GET TTL PULLUPS')
        # check 
        if(not isinstance(r,PacketStandard)) :          return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber() != 110     ) :           return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()       != (ttlpullups,) ) :     return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True)
    

    def SynConfig(self) -> TestResult : 
        synconfig = 3
        SyncConfig_bits = self.pod.DecodeSyncConfigBits(3)
        # set
        r = self.pod.WriteRead('SET SYNC CONFIG', synconfig)
        # check 
        if(  not isinstance(r,Packet)) :                return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :        return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 127     ) :          return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()        != None ) :             return TestResult(False, 'Packet has incorrect payload.')
        # get
        r = self.pod.WriteRead('GET SYNC CONFIG')
        # check 
        if(not isinstance(r,PacketStandard)) :          return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber() != 126     ) :           return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()      != (SyncConfig_bits) ) :  return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True)
    
    
    def Stimulus(self) -> TestResult : 
        stimulus = (0, 1000, 0, 500, 0, 5, 2)
        # set
        r = self.pod.WriteRead('SET STIMULUS', stimulus)
        expected_payload = (0, 1000, 0, 500, 0, 5, self.pod.DecodeStimulusConfigBits(2))
        # check 
        if(  not isinstance(r,Packet)) :                return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :        return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 102     ) :          return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()        != None ) :             return TestResult(False, 'Packet has incorrect payload.')
        # get
        r = self.pod.WriteRead('GET STIMULUS', 0)
        # check 
        if(not isinstance(r,PacketStandard)) :          return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber() != 101     ) :           return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()      != (expected_payload) ) : return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True)
    

    def Run_Stimulus(self) -> TestResult : 
        # set
        r = self.pod.WriteRead('RUN STIMULUS', 0)
        # check 
        if(  not isinstance(r,Packet)) :                return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :        return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 100     ) :          return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()        != (None) ) :           return TestResult(False, 'Packet has incorrect payload.')
        return TestResult(True)


    def Event_Ttl(self) -> TestResult : 
        # set
        r = self.pod.WriteRead('EVENT TTL', 0)
        r = self.pod.WriteRead('EVENT TTL', 0)
        # check 
        if(  not isinstance(r,Packet)) :                return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :        return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 134     ) :          return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()        != (0,) ) :             return TestResult(False, 'Packet has incorrect payload.')
        return TestResult(True)
    




    

  
     

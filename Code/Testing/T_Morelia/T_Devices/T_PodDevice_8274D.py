# local imports
from Testing.T_Morelia.TestProtocol import RunningTests, TestResult
from Morelia.Devices import Pod8274D
from Morelia.Packets import Packet, PacketStandard, PacketBinary4
import time

# authorship
__author__      = "Sree Kondi"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Sree Kondi", "Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"


class T_Pod8274D : 
    
    def __init__(self, port: str = '', preampGain: int = 10, forbidden: list[str] = [] ) -> None :
        # get port from user 
        if(port == '') : 
            print('~~~~~~~~~~ 8274D ~~~~~~~~~~')
            self.port: str = Pod8274D.ChoosePort(forbidden)
            print('~~~~~~~~~~~~~~~~~~~~~~~~~~~~')
        else : 
            self.port = port
        # create pod device object 
        self.pod: Pod8274D = Pod8274D(self.port)
      
    
    def RunTests(self, printTests: bool = True) -> tuple[int,int]: 
            """Run all tests on PodApi.Packets.PacketStandard

            Args:
                printTests (bool, optional): Make True to print the test results and messages. Defaults to True.
            
            Returns:
                tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
            """

            # collect all tests
            tests = {
                "1. Ping:\t\t"              : self.Ping,
                "1. Type:\t\t"              : self.Type,
                "3. FirmVer:\t\t"           : self.FirmVer,
                "4. Local Scan:\t\t"        : self.LocalScan,
                "5. ConnectByAddress:\t"    : self.ConnectByAddress,
                "6. SampleRate:\t\t"        : self.SampleRate,
                "7. Period:\t\t"            : self.Period,

            }
            return RunningTests.RunTests(tests, 'Pod8274D', printTests=printTests)


    def Ping(self) -> TestResult : 
        # call command
        r = self.pod.WriteRead('PING')
        # check 
        if(  not isinstance(r,Packet)) :                return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :        return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 2    ) :             return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()        != None ) :             return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good
        return TestResult(True)
    

    def Type(self) -> TestResult : 
        # call command
        r = self.pod.WriteRead('TYPE')
        # check 
        if(  not isinstance(r,Packet)) :                return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :        return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 8     ) :            return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()        != (46,) ) :            return TestResult(False, 'Packet has incorrect payload.')
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
    
    
    def LocalScan(self) -> TestResult :  ################## 
        # call command
        r = self.pod.WriteRead('LOCAL SCAN', (1))
        # check 
        if(r['Command Number']!= 101     ) :             return TestResult(False, 'Packet has an incorrect command number.')
        if(r['Payload'] == None ) :                      return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good
        return TestResult(True)


    def ConnectByAddress(self) -> TestResult : 
        # call command
        r = self.pod.WriteRead('CONNECT BY ADDRESS', (0, 13, 111, 254, 61, 150))
        connected_payload = (49152,)
        # check 
        if(  not isinstance(r,Packet)) :                return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :        return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 222     ) :          return TestResult(False, 'Packet has an incorrect command number.')
        elif(not isinstance(r.Payload(), tuple) 
             or (r.Payload()) != connected_payload) :   return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good
        return TestResult(True)


    def SampleRate(self) -> TestResult : 
        # set
        samplerate = 2
        r = self.pod.WriteRead('SET SAMPLE RATE', (samplerate))
        # check 
        if(  not isinstance(r,Packet)) :                return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :        return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 210     ) :          return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()        == None ) :             return TestResult(False, 'Packet has incorrect payload.')
        # get
        r = self.pod.WriteRead('GET SAMPLE RATE')
        if(r != (samplerate)) :                         return TestResult(False, 'Packet has incorrect payload.')
        #otherwise good 
        return TestResult(True)
    


    def Period(self) -> TestResult : 
        # set
        r = self.pod.WriteRead('SET PERIOD', 3)
        # check 
        if(  not isinstance(r,Packet)) :                return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :        return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber()  != 211     ) :          return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()        == None ) :             return TestResult(False, 'Packet has incorrect payload.')
        # get
        r = self.pod.WriteRead('GET PERIOD', ())
        # check 
        if(  not isinstance(r,Packet)) :                return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,PacketStandard)) :        return TestResult(False, 'Command did not return a standard packet')
        elif(r.CommandNumber() != 131     ) :           return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.Payload()       == None ) :              return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True)
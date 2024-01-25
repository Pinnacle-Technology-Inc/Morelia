# local imports
from Testing.T_PodApi.TestProtocol import RunningTests, TestResult
from PodApi.Devices import Pod8401HR
from PodApi.Packets import Packet, PacketStandard

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class T_Pod8401HR : 
    
    def __init__(self, port: str = '', forbidden: list[str] = [] ) -> None :
        # get port from user 
        if(port == '') : 
            print('~~~~~~~~~~ 8206HR ~~~~~~~~~~')
            useport: str = Pod8401HR.ChoosePort(forbidden)
            print('~~~~~~~~~~~~~~~~~~~~~~~~~~~~')
        else :
            useport = port
        # create pod device object 
        self.pod: Pod8401HR = Pod8401HR(useport)
        
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
        }
        return RunningTests.RunTests(tests, 'Pod8401HR', printTests=printTests)
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

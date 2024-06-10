
import sys
import os
# Add the path to the Morelia module
sys.path.append(os.path.abspath("/path/to/Morelia"))

import Path
Path.AddAPIpath()

from Morelia.Devices.PodDevice_8206HR import Pod8206HR
from Morelia.Packets import Packet, PacketStandard, PacketBinary4
from Morelia.Stream.Collect import Bucket, DrainBucket
from Morelia.Stream.Collect.DeviceValve import Valve

# enviornment imports
from threading import Thread

# authorship
__author__ = "Thresa Kelly"
__maintainer__ = "Thresa Kelly"
__credits__ = ["Sree Kondi", "Thresa Kelly", "Seth Gabbert"]
__license__ = "New BSD License"
__copyright__ = "Copyright (c) 2023, Thresa Kelly"
__email__ = "sales@pinnaclet.com"

class T_Valve:
    def __init__(self, port: str = '', preampGain: int = 10) -> None :
        # get port from user 
        if(port == '') : 
            print('~~~~~~~~~~Testing 8206HR ~~~~~~~~~~')
            self.port: str = Pod8206HR.ChoosePort()
            print('~~~~~~~~~~~~~~~~~~~~~~~~~~~~')
        else : 
            self.port = port
        # create pod device object 
        self.pod: Pod8206HR = Pod8206HR(self.port, preampGain)
        self.valve: Valve = Valve(self.pod)
        #self.Stream()
        self.RunTests()


    def RunTests(self) -> None:
        """Run all tests on the Valve class"""
        tests = {
            "1. Ping:\t\t": self.Ping,
            "2. Open Valve:\t\t": self.Open,
            "3. Drip:\t\t": self.Drip,
            "4. GetStartBytes:\t": self.GetStartBytes,
            "5. GetStopBytes:\t": self.GetStopBytes,
            "6. Close Valve:\t\t": self.Close,
        }
        for test_name, test in tests.items():
            #print(f"Running {test_name}")
            result = test()
            if result:
                print(f"{test_name} passed")
            else:
                print(f"{test_name} failed")

                
    def Ping(self) : 
        # call command
        #print("ping")
        r = self.pod.WriteRead('PING')
        # check 
        # check the command number of the response packet
        if r.CommandNumber() == 2:
            print("connected")
            return True
        else:
            print("Packet has an incorrect command number.")
            return False
        # otherwise good
    
        
    def Open(self) :
        self.valve.Open()
        r = self.pod.ReadPODpacket()
        if( not isinstance(r,Packet)) :            
            print('Command did not return a packet')
            return (False)
        elif( not isinstance(r,PacketStandard)) :    
            print ( 'Command did not return a standard packet')
            return (False)
        elif(r.CommandNumber()  != 6    ) :         
            print ( 'Packet has an incorrect command number.')
            return (False)
        elif(r.Payload()        != (1,) ) :         
            print ('Packet has incorrect payload.')
            return (False)
        # otherwise good
        return (True)
    

    def Close(self) :
        self.valve.Close()
        r = self.pod.ReadPODpacket()
        if( not isinstance(r,Packet)) :    
            print ( 'Command did not return a packet')
            return (False)
        # otherwise good
        return (True)

        
    def Drip(self) :
        packet = self.valve.Drip()
        if not isinstance(packet, Packet): 
            print('Drip did not return a Packet')
            return (False)
        elif(packet.CommandNumber()  != 180    ) :         
            print ('Packet has an incorrect command number.')
            return (False)
        return(True)
    

    def GetStartBytes(self) :
        try:
            packet = self.valve.GetStartBytes()
            if not (packet) == b'\x02000601D8\x03':
                print('Function did not return byte string')
                return (False) 
        except Exception as e:
            return (False, f"GetStartBytes test failed with exception: {e}")
        return(True)
    

    def GetStopBytes(self) :
        try:
            packet = self.valve.GetStopBytes()
            if not (packet) == b'\x02000600D9\x03':
                print('Function did not return byte string')
                return (False) 
        except Exception as e:
            return (False, f"GetStopBytes test failed with exception: {e}")
        return(True)
    
        

if __name__ == "__main__":
    tester = T_Valve()
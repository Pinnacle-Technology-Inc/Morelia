# local imports
from Testing.T_Morelia.TestProtocol import RunningTests, TestResult
from Morelia.Devices import Pod8401HR, Preamp
from Morelia.packet import PodPacket, ControlPacket, PrimaryChannelMode, SecondaryChannelMode
from Morelia.packet.data import DataPacket8401HR

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
            print('~~~~~~~~~~ 8401HR ~~~~~~~~~~')
            self.port: str = Pod8401HR.ChoosePort(forbidden)
            print('~~~~~~~~~~~~~~~~~~~~~~~~~~~~')
        else :
            self.port = port
        
        #random values for testing
        primary_channel_modes = (
          PrimaryChannelMode.EEG_EMG,
          PrimaryChannelMode.EEG_EMG,
          PrimaryChannelMode.EEG_EMG,
          PrimaryChannelMode.EEG_EMG
        )

        secondary_channel_modes = (
                SecondaryChannelMode.DIGITAL, 
                SecondaryChannelMode.ANALOG,
                SecondaryChannelMode.DIGITAL,
                SecondaryChannelMode.DIGITAL,
                SecondaryChannelMode.ANALOG,
                SecondaryChannelMode.DIGITAL
            )

      # create pod device object, random preamp chosen
        self.pod: Pod8401HR = Pod8401HR(self.port, Preamp.Preamp8406_SE, primary_channel_modes, secondary_channel_modes)
        
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
            "5. Highpass:\t\t"      : self.Highpass,
            "6. Lowpass:\t\t"       : self.Lowpass,
            "7. DC Mode:\t\t"       : self.Dc,
            "8. Bias:\t\t"          : self.Bias,
            "9. EXT:\t\t\t"         : self.Ext,
            "10. Ground:\t\t"       : self.Ground,
            "11. TTL:\t\t"          : self.Ttl,
            "12. SS Config:\t\t"    : self.Ss,
            "13. Mux Mode:\t\t"     : self.Mux,
            "13. Stream:\t\t"       : self.Stream,
        }
        return RunningTests.RunTests(tests, 'Pod8401HR', printTests=printTests)
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
        elif(r.payload        != (0x31,) ) :      return TestResult(False, 'Packet has incorrect payload.')
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
        sampleRate: int = 2500
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
    
    def Highpass(self) -> TestResult : 
        channel = 0 
        highPass_Hz = 1
        # set
        self.pod.WriteRead('SET HIGHPASS', (channel, highPass_Hz))
        # get
        r = self.pod.WriteRead('GET HIGHPASS', channel)
        # check 
        if(  not isinstance(r,PodPacket)) :            return TestResult(False, 'Command did not return a packet')
        elif(not isinstance(r,ControlPacket)) :    return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number != 102     ) :       return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.payload       != (highPass_Hz,) ) : return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True)
    
    def Lowpass(self) -> TestResult : 
        channel = 0
        lowPass_Hz = 400
        # set
        self.pod.WriteRead('SET LOWPASS', (channel, lowPass_Hz))
        # get
        r = self.pod.WriteRead('GET LOWPASS', channel)
        # check 
        if(not isinstance(r,ControlPacket)) :      return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number != 104     ) :       return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.payload       != (lowPass_Hz,) ) : return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True)
    
    def Dc(self) -> TestResult : 
        channel = 0
        dcMode = 1
        # set
        self.pod.WriteRead('SET DC MODE', (channel, dcMode))
        # get
        r = self.pod.WriteRead('GET DC MODE', channel)
        # check 
        if(not isinstance(r,ControlPacket)) :      return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number != 106     ) :       return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.payload       != (dcMode,) ) :     return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True)
    
    def Bias(self) -> TestResult : 
        channel = 0
        bias_V = 0.6
        bias_dac = self.pod.CalculateBiasDAC_GetDACValue(bias_V)
        # set
        self.pod.WriteRead('SET BIAS', (channel, bias_dac))
        # get
        r = self.pod.WriteRead('GET BIAS', channel)
        # check 
        if(not isinstance(r,ControlPacket)) :      return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number != 112     ) :       return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.payload       != (bias_dac,) ) :   return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True)    
    
    def Ext(self) -> TestResult : 
        ext0 = 0
        # set
        self.pod.WriteRead('SET EXT0', ext0)
        # get
        r = self.pod.WriteRead('GET EXT0 VALUE')
        # check 
        if(not isinstance(r,ControlPacket)) :      return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number != 114     ) :       return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.payload       != (ext0,) ) :       return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True) 
    
    def Ground(self) -> TestResult : 
        channelGrounded = self.pod.GetChannelBitmask(a=1, b=1, c=0, d=0)
        # set
        self.pod.WriteRead('SET INPUT GROUND', channelGrounded)
        # get
        r = self.pod.WriteRead('GET INPUT GROUND')
        # check 
        if(not isinstance(r,ControlPacket)) :      return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number != 122     ) :       return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.payload != (channelGrounded,) ) :  return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True) 
    
    def Ttl(self) -> TestResult : 
        ttl = self.pod.GetTTLbitmask(ext0=0,ext1=1,ttl4=0,ttl3=0,ttl2=1,ttl1=1)
        # set
        self.pod.WriteRead('SET TTL CONFIG', (ttl,ttl))
        # get config
        r = self.pod.WriteRead('GET TTL CONFIG')        
        # check 
        ttlConfig = ({'EXT0': 0, 'EXT1': 1, 'TTL4': 0, 'TTL3': 0, 'TTL2': 1, 'TTL1': 1}, {'EXT0': 0, 'EXT1': 1, 'TTL4': 0, 'TTL3': 0, 'TTL2': 1, 'TTL1': 1})
        if(not isinstance(r,ControlPacket)) :      return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number != 128     ) :       return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.payload != ttlConfig ) :           return TestResult(False, 'Packet has incorrect payload.')
        # get channel
        channel = 0
        r = self.pod.WriteRead('GET TTL ANALOG', channel)
        # check 
        if(not isinstance(r,ControlPacket)) :      return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number != 134     ) :       return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.payload != (channel,) ) :          return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True) 

    def Ss(self) -> TestResult : 
        channel = 0
        ss = self.pod.GetSSConfigBitmask(gain=1,highpass=1)
        # set
        self.pod.WriteRead('SET SS CONFIG', (channel,ss))
        # get
        r = self.pod.WriteRead('GET SS CONFIG', channel)
        # check 
        if(not isinstance(r,ControlPacket)) :      return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number != 130     ) :       return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.payload != (ss,) ) :               return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True) 
    
    def Mux(self) -> TestResult : 
        muxMode = 0
        # set
        self.pod.WriteRead('SET MUX MODE', muxMode)
        # get
        r = self.pod.WriteRead('GET MUX MODE')
        # check 
        if(not isinstance(r,ControlPacket)) :      return TestResult(False, 'Command did not return a standard packet')
        elif(r.command_number != 133     ) :       return TestResult(False, 'Packet has an incorrect command number.')
        elif(r.payload != (muxMode,) ) :          return TestResult(False, 'Packet has incorrect payload.')
        # otherwise good 
        return TestResult(True) 

    def Stream(self) -> TestResult :
        # call command
        self.pod.WritePacket('STREAM', 1) 
        self.pod.WritePacket('STREAM', 0) 
        # read a couple packets
        result = TestResult(True)
        for i in range(3) : 
            r = self.pod.ReadPODpacket()
            if(isinstance(r,ControlPacket)) : 
                if(r.command_number != 6 ) :        
                    result = TestResult(False, 'Packet has an incorrect command number.')
                    break
                elif(r.payload != (1,) and r.payload != (0,)) :         
                    result = TestResult(False, 'Packet has incorrect payload.')
                    break
            elif( not isinstance(r,DataPacket8401HR)) : 
                result = TestResult(False, 'Command did not return a binary5 packet')
                break

        # clean out data 
        self.pod.FlushPort()
        return result

"""
POD_8401HR handles communication using an 8401-HR POD device. 
"""

# local imports 
from BasicPodProtocol       import POD_Basics
from PodPacketHandling      import POD_Packets
from PodCommands            import POD_Commands

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class POD_8401HR(POD_Basics) : 


    # ============ GLOBAL CONSTANTS ============    ========================================================================================================================


    # number of bytes for a Binary 5 packet 
    __B5LENGTH : int = 31
    # number of binary bytes for a Binary 5 packet 
    __B5BINARYLENGTH : int = __B5LENGTH - 8 # length minus STX(1), command number(4), checksum(2), ETX(1) || 31 - 8 = 23

    __CHANNELMAPALL : dict = {
        '8407-SE'      : {'A':'Bio' , 'B':'EEG1', 'C':'EMG' , 'D':'EEG2'},
        '8407-SL'      : {'A':'Bio' , 'B':'EEG1', 'C':'EMG' , 'D':'EEG2'},
        '8407-SE3'     : {'A':'Bio' , 'B':'EEG1', 'C':'EEG3', 'D':'EEG2'},
        '8407-SE4'     : {'A':'EEG4', 'B':'EEG1', 'C':'EEG3', 'D':'EEG2'},
        '8407-SE31M'   : {'A':'EEG3', 'B':'EEG1', 'C':'EMG' , 'D':'EEG2'},
        '8407-SE-2BIO' : {'A':'Bio1', 'B':'Bio2', 'C':'EMG' , 'D':'EEG2'},
        '8407-SL-2BIO' : {'A':'Bio1', 'B':'Bio2', 'C':'EMG' , 'D':'EEG2'},
        '8406-SE31M'   : {'A':'EMG' , 'B':'EEG1', 'C':'EEG3', 'D':'EEG2'},
        '8406-BIO'     : {'A':'Bio' , 'B':'NC'  , 'C':'NC'  , 'D':'NC'  },
        '8406-2BIO'    : {'A':'Bio1', 'B':'Bio2', 'C':'NC'  , 'D':'NC'  },
        '8406-EEG2BIO' : {'A':'Bio1', 'B':'EEG1', 'C':'EMG' , 'D':'Bio2'},
        '8406-SE'      : {'A':'Bio' , 'B':'EEG1', 'C':'EMG' , 'D':'EEG2'},
        '8406-SL'      : {'A':'Bio' , 'B':'EEG1', 'C':'EMG' , 'D':'EEG2'},
        '8406-SE3'     : {'A':'Bio' , 'B':'EEG1', 'C':'EEG3', 'D':'EEG2'},
        '8406-SE4'     : {'A':'EEG4', 'B':'EEG1', 'C':'EEG3', 'D':'EEG2'}
    }

    # ============ DUNDER METHODS ============      ========================================================================================================================
    

    def __init__(self, port: str|int, preampName: str, ssGain:dict[str,int|None]={'A':None,'B':None,'C':None,'D':None}, preampGain:dict[str,int|None]={'A':None,'B':None,'C':None,'D':None}, baudrate:int=9600) -> None :
        # initialize POD_Basics
        super().__init__(port, baudrate=baudrate) 

        # get constants for adding commands 
        U8  = POD_Commands.U8()
        U16 = POD_Commands.U16()
        B5  = POD_8401HR.__B5BINARYLENGTH
        # remove unimplemented commands 
        self._commands.RemoveCommand(5)  # STATUS
        self._commands.RemoveCommand(10) # SAMPLE RATE
        self._commands.RemoveCommand(11) # BINARY
        # add device specific commands
        self._commands.AddCommand( 100, 'GET SAMPLE RATE',      (0,),       (U16,),     False  ) # Gets the current sample rate of the system, in Hz
        self._commands.AddCommand( 101, 'SET SAMPLE RATE',      (U16,),     (0,),       False  ) # Sets the sample rate of the system, in Hz.  Valid values are 2000 - 20000 currently
        self._commands.AddCommand( 102,	'GET HIGHPASS',	        (U8,),	    (U8,),      False  ) # Reads the highpass filter value for a channel.  Requires the channel to read, returns 0-3, 0 = 0.5Hz, 1 = 1Hz, 2 = 10Hz, 3 = DC / No Highpass 
        self._commands.AddCommand( 103,	'SET HIGHPASS',	        (U8, U8),	(0,),       False  ) # Sets the highpass filter for a channel. Requires channel to set, and filter value.  Values are the same as returned in GET HIGHPASS
        self._commands.AddCommand( 104,	'GET LOWPASS',	        (U8,),	    (U16,),     False  ) # Gets the lowpass filter for the desired channel.  Requires the channel to read, Returns the value in Hz
        self._commands.AddCommand( 105,	'SET LOWPASS',	        (U8, U16),	(0,),       False  ) # Sets the lowpass filter for the desired channel to the desired value (21 - 15000) in Hz.   Requires the channel to read, and value in Hz.
        self._commands.AddCommand( 106,	'GET DC MODE',	        (U8,),	    (U8,),      False  ) # Gets the DC mode for the channel.   Requires the channel to read, returns the value 0 = Subtract VBias, 1 = Subtract AGND.  Typically 0 for Biosensors, and 1 for EEG/EMG
        self._commands.AddCommand( 107,	'SET DC MODE',	        (U8, U8),	(0,),       False  ) # Sets the DC mode for the selected channel.   Requires the channel to read, and value to set.  Values are the same as in GET DC MODE
        self._commands.AddCommand( 112,	'GET BIAS',	            (U8,),	    (U16,),     False  ) # Gets the bias on a given channel.  Returns the DAC value as a 16-bit 2's complement value, representing a value from +/- 2.048V
        self._commands.AddCommand( 113,	'SET BIAS',	            (U8, U16),	(0,),       False  ) # Sets the bias on a given channel.  Requires the channel and DAC value as specified in GET BIAS.  Note that for most preamps, only channel 0/A DAC values are used. This can cause issues with bias subtraction on preamps with multiple bio chanenls
        self._commands.AddCommand( 114,	'GET EXT0 VALUE',	    (0,),	    (U16,),     False  ) # Reads the analog value on the EXT0 pin.  Returns an unsigned 12-bit value, representing a 3.3V input.  This is normally used to identify preamps.  Note that this function takes some time and blocks, so it should not be called during data acquisition if possible
        self._commands.AddCommand( 115,	'GET EXT1 VALUE',	    (0,),	    (U16,),     False  ) # Reads the analog value on the EXT1 pin.  Returns an unsigned 12-bit value, representing a 3.3V input.  This is normally used to identify if an 8480 is present.  Similar caveat re blocking as GET EXT0 VALUE
        self._commands.AddCommand( 116,	'SET EXT0',	            (U8,),	    (0,),       False  ) # Sets the digital value of EXT0, 0 or 1
        self._commands.AddCommand( 117,	'SET EXT1',	            (U8,),	    (0,),       False  ) # Sets the digital value of EXT1, 0 or 1
        self._commands.AddCommand( 121,	'SET INPUT GROUND',	    (U8,),	    (0,),       False  ) # Sets whether channel inputs are grounded or connected to the preamp.  Bitfield, bits 0-3, high nibble should be 0s.  0=Grounded, 1=Connected to Preamp
        self._commands.AddCommand( 122,	'GET INPUT GROUND',	    (0,),	    (U8,),      False  ) # Returns the bitmask value from SET INPUT GROUND
        self._commands.AddCommand( 127,	'SET TTL CONFIG',	    (U8, U8),	(0,),       False  ) # Configures the TTL pins.  First argument is output setup, 0 is open collector and 1 is push-pull.  Second argument is input setup, 0 is analog and 1 is digital.  Bit 7 = EXT0, bit 6 = EXT1, bits 4+5 unused, bits 0-3 TTL pins
        self._commands.AddCommand( 128,	'GET TTL CONFIG',	    (0,),	    (U8, U8),   False  ) # Gets the TTL config byte, values are as per SET TTL CONFIG
        self._commands.AddCommand( 129,	'SET TTL OUTS',	        (U8, U8),	(0,),       False  ) # Sets the TTL pins.  First byte is a bitmask, 0 = do not modify, 1=modify.  Second byte is bit field, 0 = low, 1 = high
        self._commands.AddCommand( 130,	'GET SS CONFIG',	    (U8,),	    (U8,),      False  ) # Gets the second stage gain config.  Requires the channel and returins a bitfield. Bit 0 = 0 for 0.5Hz Highpass, 1 for DC Highpass.  Bit 1 = 0 for 5x gain, 1 for 1x gain
        self._commands.AddCommand( 131,	'SET SS CONFIG',	    (U8, U8),	(0,),       False  ) # Sets the second stage gain config.  Requires the channel and a config bitfield as per GET SS CONFIG
        self._commands.AddCommand( 132,	'SET MUX MODE',	        (U8,),	    (0,),       False  ) # Sets mux mode on or off.  This causes EXT1 to toggle periodically to control 2BIO 3EEG preamps.  0 = off, 1 = on
        self._commands.AddCommand( 133,	'GET MUX MODE',	        (0,),	    (U8,),      False  ) # Gets the state of mux mode.  See SET MUX MODE
        self._commands.AddCommand( 134,	'GET TTL ANALOG',	    (U8,),	    (U16,),     False  ) # Reads a TTL input as an analog signal.  Requires a channel to read, returns a 10-bit analog value.  Same caveats and restrictions as GET EXTX VALUE commands.  Normally you would just enable an extra channel in Sirenia for this.
        self._commands.AddCommand( 181, 'BINARY5 DATA', 	    (0,),	    (B5,),      True   ) # Binary data packets, enabled by using the STREAM command with a '1' argument. 

        # verify that dictionaries are correct structure
        goodKeys = ['A','B','C','D'].sort() # CH0, CH1, CH2, CH3
        if(list(ssGain.keys()).sort() != goodKeys) : 
            raise Exception('[!] The ssGain dictionary has improper keys; keys must be [\'A\',\'B\',\'C\',\'D\'].')
        if(list(preampGain.keys()).sort() != goodKeys) : 
            raise Exception('[!] The preampGain dictionary has improper keys; keys must be [\'A\',\'B\',\'C\',\'D\'].')

        # second stage gain 
        for value in ssGain.values() :
            # both biosensors and EEG/EMG have ssGain. None when no connect 
            if(value != 1 and value != 5 and value != None): 
                raise Exception('[!] The ssGain must be 1 or 5; set ssGain to None if no-connect.')
        self._ssGain : dict[str,int|None] = ssGain 

        # preamplifier gain
        for value in preampGain.values() :
            # None when biosensor or no connect 
            if(value != 10 and value != 100 and value != None): 
                raise Exception('[!] EEG/EMG preampGain must be 10 or 100. For biosensors, the preampGain is None.')
        self._preampGain : dict[str,int|None] = preampGain
    

    # ============ PUBLIC METHODS ============      ========================================================================================================================
    

    
    # ------------ OVERWRITE ------------           ------------------------------------------------------------------------------------------------------------------------
    
    
    @staticmethod
    def UnpackPODpacket_Binary(msg: bytes) -> dict[str,bytes] :
        # Binary 5 format = 
        #   STX (1) + command (4) + packet number (1) + status (1) + channels (9) + analog inputs (12) + checksum (2) + ETX (1)
        MINBYTES = POD_8401HR.__B5LENGTH

        # get number of bytes in message
        packetBytes = len(msg)

        # message must have enough bytes, start with STX, or end with ETX
        if(    (packetBytes != MINBYTES)
            or (msg[0].to_bytes(1,'big') != POD_Packets.STX()) 
            or (msg[packetBytes-1].to_bytes(1,'big') != POD_Packets.ETX())
        ) : 
            raise Exception('Cannot unpack an invalid POD packet.')
        
        # create dict and separate message parts
        msg_unpacked = {
            'Command Number'    : msg[1:5],
            'Packet #'          : msg[5].to_bytes(1,'big'),
            'Status'            : msg[6].to_bytes(1,'big'),
            'Channels'          : msg[7:16], 
            'Analog EXT0'       : msg[16:18],
            'Analog EXT1'       : msg[18:20],
            'Analog TTL1'       : msg[20:22],
            'Analog TTL2'       : msg[22:24],
            'Analog TTL3'       : msg[24:26],
            'Analog TTL4'       : msg[26:28]
        }

        # return unpacked POD command
        return(msg_unpacked)


    def TranslatePODpacket_Binary(self, msg: bytes) -> dict[str,int|float] : 
        # unpack parts of POD packet into dict
        msgDict = POD_8401HR.UnpackPODpacket_Binary(msg)
        # translate the binary ascii encoding into a readable integer
        msgDictTrans = {}
        # basics 
        msgDictTrans['Command Number']  = POD_Packets.AsciiBytesToInt(  msgDict['Command Number'] )
        msgDictTrans['Packet #']        = POD_Packets.BinaryBytesToInt( msgDict['Packet #'] )
        msgDictTrans['Status']          = POD_Packets.BinaryBytesToInt( msgDict['Status'] )
        # dont add channel if no connect (NC)
        if(self._ssGain['D'] != None) :
            msgDictTrans['D'] = POD_8401HR._Voltage_PrimaryChannels( 
                                                    POD_Packets.BinaryBytesToInt_Split(msgDict['Channels'][0:3], 24, 6), # |  7  CH3 17~10          |  8 CH3 9~2   |  9 CH3 1~0, CH2 17~12 | --> cut           bottom 6 bits
                                                    self._ssGain['D'], self._preampGain['D'] )
        if(self._ssGain['C'] != None) :
            msgDictTrans['C'] = POD_8401HR._Voltage_PrimaryChannels( 
                                                    POD_Packets.BinaryBytesToInt_Split(msgDict['Channels'][2:5], 22, 4), # |  9  CH3 1~0, CH2 17~12 | 10 CH2 11~4  | 11 CH2 3~0, CH1 17~14 | --> cut top 2 and bottom 4 bits
                                                    self._ssGain['C'], self._preampGain['C'] )
        if(self._ssGain['B'] != None) :
            msgDictTrans['B'] = POD_8401HR._Voltage_PrimaryChannels( 
                                                    POD_Packets.BinaryBytesToInt_Split(msgDict['Channels'][4:7], 20, 2), # | 11  CH2 3~0, CH1 17~14 | 12 CH1 13~6  | 13 CH1 5~0, CH0 17~16 | --> cut top 4 and bottom 2 bits
                                                    self._ssGain['B'], self._preampGain['B'] )
        if(self._ssGain['A'] != None) :
            msgDictTrans['A'] = POD_8401HR._Voltage_PrimaryChannels( 
                                                    POD_Packets.BinaryBytesToInt_Split(msgDict['Channels'][6:9], 18, 0), # | 13  CH1 5~0, CH0 17~16 | 14 CH0 15~8  | 15 CH0 7~0            | --> cut top 6              bits
                                                    self._ssGain['A'], self._preampGain['A'] )
        # add analogs 
        msgDictTrans['Analog EXT0']     = POD_8401HR._Voltage_SecondaryChannels( POD_Packets.BinaryBytesToInt(msgDict['Analog EXT0']) ) 
        msgDictTrans['Analog EXT1']     = POD_8401HR._Voltage_SecondaryChannels( POD_Packets.BinaryBytesToInt(msgDict['Analog EXT1']) )
        msgDictTrans['Analog TTL1']     = POD_8401HR._Voltage_SecondaryChannels( POD_Packets.BinaryBytesToInt(msgDict['Analog TTL1']) )
        msgDictTrans['Analog TTL2']     = POD_8401HR._Voltage_SecondaryChannels( POD_Packets.BinaryBytesToInt(msgDict['Analog TTL2']) )
        msgDictTrans['Analog TTL3']     = POD_8401HR._Voltage_SecondaryChannels( POD_Packets.BinaryBytesToInt(msgDict['Analog TTL3']) )
        msgDictTrans['Analog TTL4']     = POD_8401HR._Voltage_SecondaryChannels( POD_Packets.BinaryBytesToInt(msgDict['Analog TTL4']) )
        
        # return translated unpacked POD packet 
        return(msgDictTrans)


    def TranslatePODpacket(self, msg: bytes) -> dict[str,int|dict[str,int]] : 
        # get command number (same for standard and binary packets)
        cmd = POD_Packets.AsciiBytesToInt(msg[1:5])
        # these commands have some specific formatting 
        specialCommands = [127, 128, 129] # 127 SET TTL CONFIG # 128 GET TTL CONFIG # 129 SET TTL OUTS
        if(cmd in specialCommands):
            msgDict = POD_Basics.UnpackPODpacket_Standard(msg)
            transdict = { 'Command Number' : POD_Packets.AsciiBytesToInt( msgDict['Command Number'] ) } 
            if('Payload' in msgDict) : 
                transdict['Payload'] = ( self._TranslateTTLByte(msgDict['Payload'][:2]), self._TranslateTTLByte(msgDict['Payload'][2:]))
            return(transdict)
        # message is binary 
        elif(self._commands.IsCommandBinary(cmd)): 
            return(self.TranslatePODpacket_Binary(msg))
        # standard packet 
        else: 
            return(self.TranslatePODpacket_Standard(msg)) # TranslatePODpacket_Standard does not handle TTL well, hence elif statements 


    # ------------ HELPER ------------           ------------------------------------------------------------------------------------------------------------------------
    

    @staticmethod
    def GetChannelMapForPreampDevice(preampName: str) -> dict[str,str]|None :
        if(preampName in POD_8401HR.__CHANNELMAPALL) : 
            return(POD_8401HR.__CHANNELMAPALL[preampName])
        else : 
            return(None) # no device matched


    @staticmethod
    def GetSupportedPreampDevices() -> list[str]: 
        return(list(POD_8401HR.__CHANNELMAPALL.keys()))


    @staticmethod
    def IsPreampDeviceSupported(name: str) -> bool : 
        return(name in POD_8401HR.__CHANNELMAPALL)    


    @staticmethod
    def GetTTLbitmask_Int(ext0:bool=0, ext1:bool=0, ttl4:bool=0, ttl3:bool=0, ttl2:bool=0, ttl1:bool=0) -> int :
        # use this for the argument/return for TTL-specific commands 
        # (msb) Bit 7 = EXT0, bit 6 = EXT1, bits 4+5 unused, bits 0-3 TTL pins (lsb) 
        return( 0 | (ext0 << 7) | (ext1 << 6) | (ttl4 << 3) | (ttl3 << 2) | (ttl2 << 1) | ttl1 )


    @staticmethod
    def GetSSConfigBitmask_int(gain: int, highpass: float) -> int :
        # interpret highpass (lsb)
        if(highpass == 0.0) :   bit0 = True  # DC highpass
        else:                   bit0 = False # AC 0.5Hz highpass 
        # interpret gain (msb)
        if(gain == 1) : bit1 = True  # 1x gain 
        else:           bit1 = False # 5x gain 
        # bit shifting to get integer bitmask
        return( 0 | (bit1 << 1) | bit0 ) # use for 'SET SS CONFIG' command

    
    @staticmethod
    def CalculateBiasDAC_GetVout(value: int|float) -> float :
        # Use this method for GET/SET BIAS commands 
        # DAC Value is 16 Bits 2's complement (aka signed) corresponding to the output bias voltage 
        return( (value / 32768.) * 2.048 )


    @staticmethod
    def CalculateBiasDAC_GetDACValue(vout: int|float) -> int :
        # Use this method for GET/SET BIAS commands 
        # DAC Value is 16 Bits 2's complement (aka signed) corresponding to the output bias voltage 
        return(int( (vout / 2.048) * 32768. ))
    

    # ============ PROTECTED METHODS ============      ========================================================================================================================    
    

    # ------------ CONVERSIONS ------------           ------------------------------------------------------------------------------------------------------------------------


    @staticmethod
    def _TranslateTTLByte(ttlByte: bytes) -> dict[str,int] : 
        return({
            'EXT0' : POD_Packets.ASCIIbytesToInt_Split(ttlByte, 8, 7),
            'EXT1' : POD_Packets.ASCIIbytesToInt_Split(ttlByte, 7, 6),
            'TTL4' : POD_Packets.ASCIIbytesToInt_Split(ttlByte, 4, 3),
            'TTL3' : POD_Packets.ASCIIbytesToInt_Split(ttlByte, 3, 2),
            'TTL2' : POD_Packets.ASCIIbytesToInt_Split(ttlByte, 2, 1),
            'TTL1' : POD_Packets.ASCIIbytesToInt_Split(ttlByte, 1, 0)
        })
    

    @staticmethod
    def _Voltage_PrimaryChannels(value: int, ssGain:int|None=None, PreampGain:int|None=None) -> float :
        if(ssGain != None and PreampGain == None) : 
            return(POD_8401HR._Voltage_PrimaryChannels_Biosensor(value, ssGain))
        elif(ssGain != None):
            return(POD_8401HR._Voltage_PrimaryChannels_EEGEMG(value, ssGain, PreampGain))
        else: 
            return(value) # no connect! this is noise 


    @staticmethod
    def _Voltage_PrimaryChannels_EEGEMG(value: int, ssGain: int, PreampGain: int) -> float : 
        # Channels configured as EEG/EMG channels (0.4/1/10 Hz highpass filter, second stage 0.5Hz Highpass, second stage 5x)
        voltageAtADC = (value / 262144.0) * 4.096 # V
        totalGain    = 10.0 * ssGain * PreampGain # SSGain = 1 or 5, PreampGain = 10 or 100
        realVoltage  = (voltageAtADC - 2.048) / totalGain # V
        return(realVoltage)
    

    @staticmethod
    def _Voltage_PrimaryChannels_Biosensor(value: int, ssGain: int) -> float : 
        # Channels configured as biosensor channels (DC highpass filter, second stage DC mode, second stage 1x)
        voltageAtADC = (value / 262144.0) * 4.096 # V
        totalGain    = 1.557 * ssGain * 1E7 # SSGain = 1 or 5
        realVoltage  = (voltageAtADC - 2.048) / totalGain # V
        return(realVoltage)


    @staticmethod
    def _Voltage_SecondaryChannels(value: int) -> float :
        # The additional inputs (EXT0, EXT1, TTL1-3) values are all 12-bit referenced to 3.3V.  To convert them to real voltages, the formula is as follows
        return( (value / 4096.0) * 3.3 ) # V


    # ------------ OVERWRITE ------------           ------------------------------------------------------------------------------------------------------------------------

    def _Read_Binary(self, prePacket: bytes, validateChecksum:bool=True):
        """
        Binary 5 Data Format
        -----------------------------------------------------------------------------		
        Byte    Value	                        Format      Description 
        -----------------------------------------------------------------------------		
        0	    0x02	                        Binary		STX
        1	    0	                            ASCII		Command Number Byte 0
        2	    0	                            ASCII		Command Number Byte 1
        3	    B	                            ASCII		Command Number Byte 2
        4	    5	                            ASCII		Command Number Byte 3
        5	    Packet Number 	                Binary		A rolling value that increases with each packet, and rolls over to 0 after it hits 255
        6	    Status	                        Binary		Status byte, currently unused
        7	    CH3 17~10	                    Binary		Top 8 bits of CH3.  Data is 18 bits, packed over 3 bytes.  Because of this the number of bits in each byte belonging to each chanenl changes.  Values are sent MSB/MSb first
        8	    CH3 9~2	                        Binary		Middle 8 bits of CH3
        9	    CH3 1~0, CH2 17~12	            Binary		Bottom 2 bits of CH3 and top 6 bits of CH2
        10	    CH2 11~4	                    Binary		Middle 8 bits of Ch2
        11	    CH2 3~0, CH1 17~14	            Binary		Bottom 4 bits of CH2 and top 4 bits of CH1
        12	    CH1 13~6	                    Binary		Middle 8 bits of CH1
        13	    CH1 5~0, CH0 17~16	            Binary		Bottom 6 bits of CH1 and top 2 bits of CH0
        14	    CH0 15~8	                    Binary		Middle 8 bits of Ch0
        15	    CH0 7~0	                        Binary		Bottom 8 bits of CH0
        16	    EXT0 Analog Value High Byte	    Binary		Top nibble of the 12-bit EXT0 analog value.  Sent MSB/MSb first
        17	    EXT0 Analog Value Low Byte	    Binary		Bottom nibble of the EXT0 value
        18	    EXT1 Analog Value High Byte	    Binary		Top nibble of the 12-bit EXT1 analog value.  Sent MSB/MSb first
        19	    EXT1 Analog Value Low Byte	    Binary		Bottom nibble of the EXT1 value
        20	    TTL1 Analog Value High Byte	    Binary		Top nibble of the TTL1 pin read as a 12-bit analog value
        21	    TTL1 Analog Value Low Byte	    Binary		Bottom nibble of the TTL2 pin analog value
        22	    TTL2 Analog Value High Byte	    Binary		Top nibble of the TTL1 pin read as a 12-bit analog value
        23	    TTL2 Analog Value Low Byte	    Binary		Bottom nibble of the TTL2 pin analog value
        24	    TTL3 Analog Value High Byte	    Binary		Top nibble of the TTL3 pin read as a 12-bit analog value
        25	    TTL3 Analog Value Low Byte	    Binary		Bottom nibble of the TTL3 pin analog value
        26	    TTL4 Analog Value High Byte	    Binary		Top nibble of the TTL4 pin read as a 12-bit analog value
        27	    TTL4 Analog Value Low Byte	    Binary		Bottom nibble of the TTL4 pin analog value
        28	    Checksum MSB	                ASCII		Checksum
        29	    Checksum LSB	                ASCII		Checksum 
        30	    0x03	                        Binary		ETX
        -----------------------------------------------------------------------------
        """
        # get prepacket (STX+command number) (5 bytes) + 23 binary bytes (do not search for STX/ETX) + read csm and ETX (3 bytes) (these are ASCII, so check for STX/ETX)
        packet = prePacket + self._port.Read(self.__B5BINARYLENGTH) + self._Read_ToETX(validateChecksum=validateChecksum)
        # check if checksum is correct 
        if(validateChecksum):
            if(not self._ValidateChecksum(packet) ) :
                raise Exception('Bad checksum for binary POD packet read.')
        # return complete variable length binary packet
        return(packet)
 
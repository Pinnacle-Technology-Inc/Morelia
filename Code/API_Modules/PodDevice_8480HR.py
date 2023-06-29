"""
POD_8480HR handles communication using an 8480-HR POD device. 
"""

# local imports 
from BasicPodProtocol       import POD_Basics
from PodPacketHandling      import POD_Packets
from PodCommands            import POD_Commands


# authorship
__author__      = "Sree Kondi"
__maintainer__  = "Sree Kondi"
__credits__     = ["Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Sree Kondi"
__email__       = "sales@pinnaclet.com"

class POD_8480HR(POD_Basics) : 
    # NOTE: dont forget to add docstrings to everything 

    # ============ DUNDER METHODS ============      ========================================================================================================================
    

    def __init__(self, port: str|int, baudrate:int=9600) -> None :

        super().__init__(port, baudrate=baudrate) # inheritance 
        U8  = POD_Commands.U8()
        U16 = POD_Commands.U16()
        U32 = POD_Commands.U32()

        self._commands.RemoveCommand(10) # SAMPLE RATE
        self._commands.RemoveCommand(5)
        self._commands.RemoveCommand(6)
        self._commands.RemoveCommand(9)
        self._commands.RemoveCommand(11)
    
        # add device specific commands
        self._commands.AddCommand( 100, 'RUN STIMULUS',         (U8,),                              (0,),                                False  , 'Requires U8 Channel.  Runs the stimulus on the selected channel (0 or 1).  Will generally be immediately followed by a 133 EVENT STIM START packet, and followed by a 134 EVENT STIM END packet after the stimulus completes.')
        self._commands.AddCommand( 101, 'GET STIMULUS',         (U8,),                              (U8, U16, U16, U16, U16, U32, U8),   False  , 'Requires U8 Channel.  Gets the current stimulus configuration for the selected channel.  See format below. ')
        self._commands.AddCommand( 102,	'SET STIMULUS',	        (U8, U16, U16, U16, U16, U32, U8),	(0,),                                False  , 'Sets the stimulus configuration on the selected channel.  See format below.')  
        self._commands.AddCommand( 108,	'GET TTL SETUP',	    (U8,),	                            (U8, U8),                            False  , 'Requires U8 channel.  Returns U8 config flags, and U8 debounce value in ms.  See below for config flags format.')
        self._commands.AddCommand( 109,	'SET TTL SETUP',	    (U8,U8, U8),	                    (U8, U8),                            False  , 'Sets the TTL setup for the channel.  Format is Channel, Config Flags, Debounce in ms.  See below for config flags format.')
        self._commands.AddCommand( 110,	'GET TTL PULLUPS',	    (0,),	                            (U8,),                               False  , 'Gets whether TTL pullups are enabled on the TTL lines.  0 = no pullups, non-zero = pullups enabled.')
        self._commands.AddCommand( 111,	'SET TTL PULLUPS',	    (U8,),	                            (0,),                                False  , 'Sets whether pullups are enabled on the TTL lines.  0 = pullups disabled, non-zero = pullups enabled.')
        self._commands.AddCommand( 116,	'GET LED CURRENT',	    (0,),	                            (U16, U16),                          False  , 'Gets the setting for LED current for both channels in mA.  CH0 CH1.')
        self._commands.AddCommand( 117, 'SET LED CURRENT',	    (U8, U16),	                        (0,),                                False  , 'Requires U8 channel.  Sets the selected channel LED current to the given value in mA, from 0-600.')
        self._commands.AddCommand( 118,	'GET ESTIM CURRENT',	(0,),	                            (U16, U16),                          False  , 'Gets the setting for the ESTIM current for both channels, in percentage.  CH0 then CH1.')
        self._commands.AddCommand( 119,	'SET ESTIM CURRENT',	(U8, U16),	                        (0,),                                False  , 'Requires U8 channel.  Sets the selected chanenl ESTIM current to the given value in percentage, from 0-100.')
        self._commands.AddCommand( 124,	'GET PREAMP TYPE',	    (0,),	                            (U16,),                              False  , 'Gets the store preamp value.')
        self._commands.AddCommand( 125,	'SET PREAMP TYPE',	    (U16,),	                            (0,),                                False  , 'Sets the preamp value, from 0-1023.  This should match the table in Sirenia, it is a 10-bit code that tells the 8401 what preamp is connected.  Only needed when used with an 8401. See table below.')
        self._commands.AddCommand( 126,	'GET SYNC CONFIG',	    (0,),	                            (U8,),                               False  ,  'Gets the sync config byte.  See format below.')
        self._commands.AddCommand( 127,	'SET SYNC CONFIG',	    (U8,),	                            (0,),                                False  , 'Sets the sync config byte.  See format below.')
        # The commands below are event commands and as such are outbound only.The API should handle these commands but should not send them. 
        self._commands.AddCommand( 132,	'EVENT TTL',	        (0,),	                            (U8,),                               False  , 'Indicates a TTL event has occurred on the indicated U8 TTL input.  If debounce is non-zero then this will not occur until the debounce has completed successfully.')
        self._commands.AddCommand( 133,	'EVENT STIM START',	    (0,),	                            (U8,),                               False  , 'Indicates the start of a stimulus.  Returns U8 channel.')
        self._commands.AddCommand( 134,	'EVENT STIM STOP',	    (0,),	                            (U8,),                               False  ,'Indicates the end of a stimulus. Returns U8 channel.')
        self._commands.AddCommand( 135,	'EVENT LOW CURRENT',	(0,),	                            (U8,),                               False  , 'Indicates a low current status on one or more of the LED channels.  U8 bitmask indication which channesl have low current.  Bit 0 = Ch0, Bit 1 = Ch1.')

    @staticmethod
    def StimulusConfigBits(optoElec:bool, monoBiphasic:bool, Simul:bool) -> int :
        return (0 | (Simul << 2) | (monoBiphasic << 1) | (optoElec))

    
    @staticmethod
    def SyncConfigBits(sync_level:bool, sync_idle:bool, signal_trigger:bool) -> int :
        return (0 | (signal_trigger << 2) | (sync_idle << 1) | (sync_level))


    @staticmethod    
    def TtlConfigBits(trigger: bool, stimtrig : bool, input_sync : bool):
        return (0 | (input_sync << 7) | (stimtrig << 1) | (trigger))
    

    def DecodeStimulusConfigBits(self,config: int) -> dict:
        DecodeStimulus = {
            'optoElec'      : config & 1,  
            'monoBiphasic'  : (config >> 1) & 1,  
            'Simul'         : (config >> 2) & 1,  
        }
        return DecodeStimulus

    # stimulustrial = DecodeStimulusConfigBits(6)
    # print("\nbits: ", stimulustrial)


    # TODO decode SyncConfigBits
    def DecodeSyncConfigBits(self, config: int) -> dict:
        DecodeSync = {
            'SyncLevel'     : (config) & 1,
            'SyncIdle'      : (config >> 1) & 1,
            'SignalTrigger' : (config >> 2),
        }
        return DecodeSync
    
    # synctrail = DecodeSyncConfigBits(1)
    # print("\nsyncbits: ", synctrail)


    def DecodeTTlConfigBits(self, config:int) -> dict:
        DecodeTTL = {
            'RisingFalling'  : config & 1,
            'StimulusTrig'   : (config >> 1) & 1,
            'TTLInputSync'   : (config >> 7) & 1, 
        }
        return DecodeTTL
    
    # TTLtrail = DecodeTTlConfigBits(128)
    # print("\nTTL:", TTLtrail)


    # TODO overwrite TranslatePODpacket to handle special commands (reverse the bitmasking)
    # see TranslatePODpacket in PodDevice_8401HR for example
    # example pseudocode:
    
    def TranslatePODpacket(self, msg: bytes) -> dict[str, int | bytes]:
        specialcommands = [101, 126, 108] #101 is the number for 'GET STIMULUS'
        cmd = POD_Packets.AsciiBytesToInt(msg[1:5]) #gets the command number

        print("testing...")
        print("msg", msg)
        if(cmd in specialcommands) : 
            # unpack 
            msgDict = POD_Basics.UnpackPODpacket_Standard(msg)  #breaks up the msg into dictionary with keys as 'command number' and 'payload'
            # start building translated dictionary 
            print("msgDict", msgDict)
            transdict = { 'Command Number' : POD_Packets.AsciiBytesToInt( msgDict['Command Number'] ) }   #pulling value from msgdict and changing into int
            if (cmd == 126):  #126 GET SYNC CONFIG
                # print("SYNC CONFIG")
                # print("TYPE", type(msgDict['Payload']))
                transdict = { 'Payload' : POD_Packets.AsciiBytesToInt( msgDict['Payload'] ) }  #changing the bytes to int
                transdict['Payload'] = self.DecodeSyncConfigBits(transdict['Payload'])  #putting the integer into the decode function
                print("TRANSDICTIONARY", transdict['Payload'])
            if(cmd == 108): #108 GET TTL SETUP
                transdict = { 'Payload' : POD_Packets.AsciiBytesToInt( msgDict['Payload'][:4] ) }
                #print("PAYLOAD... TTL", transdict['Payload'])
                transdict['Payload'] = self.DecodeTTlConfigBits(transdict['Payload'])
                print("TRANSDICTIONARY", transdict)
            if(cmd == 101): #101 GET STIMULUS
                transdict = { 'Payload' : POD_Packets.AsciiBytesToInt( msgDict['Payload'][-1:] ) }
                #print("PAYLOAD... STIMULS", transdict['Payload'])
                transdict['Payload'] = self.DecodeStimulusConfigBits(transdict['Payload'])
                print("TRANSDICTIONARY", transdict)
        else:
            return(self.TranslatePODpacket_Standard(msg))
                 
            
        # maintain (U8, U16x4, U32, U8) tuple structure.
        

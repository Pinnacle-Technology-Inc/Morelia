from PodApi.Devices import Pod

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Valve : 
    """Container class to start and stop streaming data from a POD device
    
    Attributes: 
            podDevice (Pod): POD device, such as an 8206-HR or 8401-HR.
            streamCmd (str | int): Command name/number for streaming data.
            streamPldStart (int | bytes | tuple[int | bytes] | None): Payload \
                to start streaming data.
            streamPldStop (int | bytes | tuple[int | bytes] | None): Payload \
                to stop streaming data.
    """
    
    def __init__(self, 
                 podDevice: Pod, 
                 streamCmd: str|int, 
                 streamPldStart: int|bytes|tuple[int|bytes]|None = None, 
                 streamPldStop: int|bytes|tuple[int|bytes]|None = None ) -> None:
        """Set instance variables.

        Args:
            podDevice (Pod): POD device, such as an 8206-HR or 8401-HR.
            streamCmd (str | int): Command name/number for streaming data.
            streamPldStart (int | bytes | tuple[int | bytes] | None, optional): \
                Payload to start streaming data. Defaults to None.
            streamPldStop (int | bytes | tuple[int | bytes] | None, optional): \
                Payload to stop streaming data. Defaults to None.
        """
        # check for valid command and payload 
        podDevice._commands.ValidateCommand(streamCmd,streamPldStart)
        podDevice._commands.ValidateCommand(streamCmd,streamPldStop)
        # set instance variables 
        self.podDevice : Pod = podDevice
        self.streamCmd : str|int = streamCmd
        self.streamPldStart : int|bytes|tuple[int|bytes] = streamPldStart
        self.streamPldStop  : int|bytes|tuple[int|bytes] = streamPldStop
        
    def Open(self):
        """Write command to start streaming.
        """
        self.podDevice.WritePacket(self.streamCmd, self.streamPldStart)
    
    def Close(self):
        """Write command to stop streaming 
        """
        self.podDevice.WritePacket(self.streamCmd, self.streamPldStop)
                

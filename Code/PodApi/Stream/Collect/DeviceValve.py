# local imports
from PodApi.Devices import Pod8206HR, Pod8401HR, Pod8274D
from PodApi.Packets import Packet

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Valve : 
    """Simple class to start and stop streaming data from a POD device.
    
    Attributes: 
            podDevice (Pod8206HR | Pod8401HR | Pod8274D): POD device, such as an 8206-HR or 8401-HR.
            streamCmd (str | int): Command name/number for streaming data.
            streamPldStart (int | bytes | tuple[int | bytes]): Payload to start streaming data.
            streamPldStop (int | bytes | tuple[int | bytes]): Payload to stop streaming data.
    """
    
    def __init__(self, podDevice: Pod8206HR|Pod8401HR|Pod8274D ) -> None:
        """Set instance variables.

        Args:
            podDevice (Pod8206HR | Pod8401HR | Pod8274D): 8206-HR or 8401-HR POD device to stream data from.
        """
        # set instance variables 
        self.podDevice : Pod8206HR|Pod8401HR|Pod8274D = podDevice
        self.streamCmd : str|int = 'STREAM' 
        self.streamPldStart : int|bytes|tuple[int|bytes] = 1
        self.streamPldStop  : int|bytes|tuple[int|bytes] = 0
        # check for valid command and payload 
        podDevice._commands.ValidateCommand(self.streamCmd,self.streamPldStart)
        podDevice._commands.ValidateCommand(self.streamCmd,self.streamPldStop)     
        # NOTE both 8206HR/8401HR/Pod8274D use the same command to start streaming. 
        # If there is a new device that uses a different command, add a method 
        # to check what type the device is (i.e isinstance(podDevice, PodClass)) 
        # and set the self.stream* instance variables accordingly.
        
    def Open(self):
        """Write command to start streaming.
        
        Raises:
            Exception: Could not connect to this POD device.
        """
        # check for good connection 
        if(not self.podDevice.TestConnection()): 
            raise Exception('[!] Could not connect to this POD device.')
        # write command 
        self.podDevice.WritePacket(self.streamCmd, self.streamPldStart)
    
    def Close(self):
        """Write command to stop streaming 
        """
        # write command without checking connection, which flushes all packets
        self.podDevice.WritePacket(self.streamCmd, self.streamPldStop)

    def Drip(self) -> Packet : 
        """Reads one packet from the POD device.

        Returns:
            Packet: POD packet beginning with STX and ending with ETX. \
                This may be a standard packet, binary packet, or an \
                unformatted packet (STX+something+ETX).
        """
        return self.podDevice.ReadPODpacket(timeout_sec=1)

    def EmptyValve(self) :
        """Reset the serial port buffer.
        """ 
        self.podDevice.FlushPort()
        
    def GetStartBytes(self) -> bytes : 
        """Gets the bytes string represeting a "start streaming data" packet.

        Returns:
            bytes: Bytes string for a self.streamCmd command and a \
                self.streamPldStart payload.
        """
        return self.podDevice.GetPODpacket( cmd=self.streamCmd, payload=self.streamPldStart)
    
    def GetStopBytes(self) -> bytes : 
        """Gets the bytes string represeting a "stop streaming data" packet.

        Returns:
            bytes: Bytes string for a self.streamCmd command and a \
                self.streamPldStop payload.
        """
        return self.podDevice.GetPODpacket( cmd=self.streamCmd, payload=self.streamPldStop)
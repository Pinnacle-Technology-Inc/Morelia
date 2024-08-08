"""POD device that streams data."""

__author__      = 'James Hurd'
__maintainer__  = 'James Hurd'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2023, James Hurd'
__email__       = 'sales@pinnaclet.com'

from typing import Self

from Morelia.Devices import Pod

class AquisitionDevice(Pod):

    def __init__(self, port: str|int, max_sample_rate: int, baudrate:int=9600, device_name: str | None =  None, 
                 get_sample_rate_cmd_no: int = 100, set_sample_rate_cmd_no: int = 101) -> None:

        super().__init__(port, baudrate=baudrate, device_name=device_name) 

        U16: int = Pod.GetU(16)
        
        self._commands.AddCommand(get_sample_rate_cmd_no, 'GET SAMPLE RATE',      (0,),       (U16,),    False,   'Gets the current sample rate of the system, in Hz.')
        self._commands.AddCommand(set_sample_rate_cmd_no, 'SET SAMPLE RATE',      (U16,),     (0,),      False,   'Sets the sample rate of the system, in Hz. Valid values are 100 - 2000 currently.')

        self._sample_rate: int = self.WriteRead('GET SAMPLE RATE').payload

        self._max_sample_rate: int = max_sample_rate

    @property
    def max_sample_rate(self) -> int:
        return self._max_sample_rate

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @sample_rate.setter
    def sample_rate(self, rate: int) -> None:
        if rate > self.max_sample_rate:
            raise ValueError(f'The maximum allowable sample rate is {self.max_sample_rate} Hz.')

        self.WriteRead('SET SAMPLE RATE', rate)
        self._sample_rate: int = rate
    
    def __enter__(self) -> Self:

        #no WriteRead, because the confirmation packet may arrive
        #after streaming data due to a race condition in the device's
        #firmware. Therefore, we leave dealing with the response packet
        #to the user.
        self.WritePacket('STREAM', 1)

        return self

    def __exit__(self, *args, **kwargs) -> None:

        self.WritePacket('STREAM', 0)
        
        #get any packets that may have arrived between the user ending stream
        #and the command being received from the device + plus the response
        #packet from earlier.
        while True:
            try:
                self.ReadPODpacket(timeout_sec=1)
            except TimeoutError:
                break
        
        #explicitly tell the context manager to propagate execptions.
        return False

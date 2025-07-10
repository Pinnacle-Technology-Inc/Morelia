"""POD device that streams data."""

__author__      = 'James Hurd'
__maintainer__  = 'James Hurd'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2023, James Hurd'
__email__       = 'sales@pinnaclet.com'

from typing import Self

from Morelia.Devices import Pod

class AcquisitionDevice(Pod):
    """
    This class is the parent of any device that can stream (i.e. data acquisiton devices).

    :param port: Serial port to be opened. Used when initializing the COM_io instance.
    :param max_sample_rate: Maximum sample rate supported by the device (in Hz).
    :param baudrate: Baud rate of the opened serial port. Default value is 9600.
    :param device_name: Virtual Name used to indentify device.
    :param get_sample_rate_cmd_no: Command number for the ``GET SAMPLE RATE`` command on the device.
    :param set_sample_rate_cmd_no: Command number for the ``SET SAMPLE RATE`` command on the device.

    """
    def __init__(self, port: str|int, max_sample_rate: int, baudrate:int=9600, device_name: str | None =  None, 
                 get_sample_rate_cmd_no: int = 100, set_sample_rate_cmd_no: int = 101) -> None:

        super().__init__(port, baudrate=baudrate, device_name=device_name) 

        UINT16: int = Pod.get_u(16)
                    
        #initialize as none so that when we ask for the sample rate later, it uses the overidden WriteRead.
        self._sample_rate: int = None

        self._max_sample_rate: int = max_sample_rate

    @property
    def max_sample_rate(self) -> int:
        """Maximum allowable sample rate."""
        return self._max_sample_rate

    @property
    def sample_rate(self) -> int:
        """Currently set sample rate."""
        if self._sample_rate is None:
            self._sample_rate = self.write_read('GET SAMPLE RATE').payload
        return self._sample_rate[0]

    @sample_rate.setter
    def sample_rate(self, rate: int) -> None:
        if rate > self.max_sample_rate:
            raise ValueError(f'The maximum allowable sample rate is {self.max_sample_rate} Hz.')

        self.write_read('SET SAMPLE RATE', (rate,))
        self._sample_rate: int = (rate,)
    
    def __enter__(self) -> Self:

        #no WriteRead, because the confirmation packet may arrive
        #after streaming data due to a race condition in the device's
        #firmware. Therefore, we leave dealing with the response packet
        #to the user.
        self.write_packet('STREAM', 1)

        return self

    def __exit__(self, *args, **kwargs) -> bool:

        self.write_packet('STREAM', 0)
        
        #get any packets that may have arrived between the user ending stream
        #and the command being received from the device + plus the response
        #packet from earlier.
        while True:
            try:
                self.read_pod_packet(timeout_sec=1)
            except TimeoutError:
                break
        
        #explicitly tell the context manager to propagate execptions.
        return False

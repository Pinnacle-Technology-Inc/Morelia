# local imports 
from Morelia.Parameters import Params

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Params8206HR(Params) :
    """Container class that stores parameters for an 8206-HR POD device.

    Attributes:
        port (str): Name of the COM port.
        sampleRate (int): Sample rate in 100-2000 Hz range.
        preamplifierGain (int): Preamplifier gain. Should be 10x or 100x.
        lowPass (tuple[int]): Low-pass for EEG/EMG in 11-500 Hz range. 
    """

    lowPassLabels: tuple[str]  = ('EEG1', 'EEG2', 'EEG3/EMG')
    """Tuple describing the items in the lowPass."""

    def __init__(self, 
                 port:              str,       
                 sampleRate:        int,       
                 preamplifierGain:  int,       
                 lowPass:           tuple[int],
                 checkForValidParams: bool = True
                ) -> None:
        """Sets the instance variables of each 8206-HR parameter. Checks if the arguments are \
        valid when checkForValidParams is True.  

        Args:
            port (str): Name of the COM port.
            sampleRate (int): Sample rate in 100-2000 Hz range.
            preamplifierGain (int): Preamplifier gain. Should be 10x or 100x.
            lowPass (tuple[int]): Low-pass for EEG/EMG in 11-500 Hz range. 
            checkForValidParams (bool, optional): Flag to raise Exceptions for invalid \
                parameters when True. Defaults to True.
        """
        self.sampleRate:        int         = int( sampleRate       ) 
        self.preamplifierGain:  int         = int( preamplifierGain ) 
        self.lowPass:           tuple[int]  = self._FixTypeInTuple( tuple(lowPass), int ) 
        super().__init__(port,checkForValidParams)


    def EEG1(self) -> int :
        """Gets the filter value of EEG1 in Hz from the low-pass. 

        Returns:
            int: EEG1 low-pass filter in Hz.
        """
        return(int(self.lowPass[0]))


    def EEG2(self) -> int :
        """Gets the filter value of EEG2 in Hz from the low-pass. 

        Returns:
            int: EEG2 low-pass filter in Hz.
        """
        return(int(self.lowPass[1]))
    

    def EEG3_EMG(self) -> int :
        """Gets the filter value of EEG3/EMG in Hz from the low-pass. 

        Returns:
            int: EEG3/EMG low-pass filter in Hz.
        """
        return(int(self.lowPass[2]))


    def GetInit(self) -> str : 
        """Builds a string that represents the Params_8206HR constructor with the \
        arguments set to the values of this class instance. 

        Returns:
            str: String that represents the Params_8206HR constructor.
        """
        return('Morelia.Parameters.Params8206HR(port=\''+self.port+'\', sampleRate='+str(self.sampleRate)+
               ', preamplifierGain='+str(self.preamplifierGain)+', lowPass='+str(self.lowPass)+')')


    def _CheckParams(self) -> None :
        """Throws an exception if Params_8206HR instance variable is an invalid value.

        Raises:
            Exception: Sample rate must be between 100-2000 Hz.
            Exception: Preamplidier gain must be 10x or 100x.
            Exception: Low-pass EEG/EMG must be between 11-500 Hz.
        """
        super()._CheckParams() 

        if(self.sampleRate < 100 or self.sampleRate > 2000 ) : 
            raise Exception('Sample rate must be between 100-2000 Hz.')
        
        if(self.preamplifierGain != 10 and self.preamplifierGain != 100 ) : 
            raise Exception('Preamplidier gain must be 10x or 100x.')
        
        for eeg in self.lowPass : 
            if(eeg < 11 or eeg > 500) :
                raise Exception('Low-pass EEG/EMG must be between 11-500 Hz.')

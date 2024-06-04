# local imports 
from Morelia.Parameters import Params

# authorship
__author__      = "Sree Kondi"
__maintainer__  = "Sree Kondi"
__credits__     = ["Sree Kondi","Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Params8480SC(Params) :
    """Container class that stores parameters for an 8401-HR POD device.

    Attributes:
        port (str): Name of the COM port.
        stimulus (tuple[int]): Stimulus configuration on selected channel.
        preamp (int): Preamp value (0-1023).
        ledCurrent (tuple[int]): Led-Current (0-600 mA) for both channels. 
        ttlPUllups (int): TTL Pullups disabled for value 0, pullups enabled for values that are non-zero.
        estimCurrent (tuple[int]): Estim-Current (0-100 %) for both channels.
        syncConfig (int): Sets Sync-Config byte.
        ttlSetup (tuple[int]): TTL-Setup for selected channel.
    """

    def __init__(self,
        port:  str,
        stimulus = tuple[int],
        preamp = int,
        ledCurrent = tuple[int],
        ttlPullups = int,
        estimCurrent = tuple[int],
        syncConfig = int,
        ttlSetup = tuple[int],                                                    
        checkForValidParams: bool = True
        ) -> None:
        """Sets the member variables of each 8480-SC parameter. Checks if the arguments are \
        valid when checkForValidParams is True.  

        Args:
            port (str): Name of the COM port.
            stimulus (tuple[int]): Stimulus configuration on selected channel.
            preamp (int): Preamp value (0-1023).
            ledCurrent (tuple[int]): Led-Current (0-600 mA) for both channels. 
            ttlPUllups (int): pullups disabled for value 0, pullups enabled for values that are non-zero.
            estimCurrent (tuple[int]): Estim-Current (0-100 %) for both channels.
            syncConfig (int): Sets Sync-Config byte.
            ttlSetup (tuple[int]): TTL-Setup for selected channel.
            checkForValidParams (bool, optional): Flag to raise Exceptions for invalid \
                parameters when True. Defaults to True.
        """
        self.stimulus:       tuple[int]  =  self._FixTypeInTuple( tuple(stimulus), int )
        self.preamp:         int         =  int( preamp)
        self.ledCurrent:     tuple[int]  =  self._FixTypeInTuple( tuple(ledCurrent), int )
        self.ttlPullups:     int         =  int( ttlPullups)
        self.estimCurrent:   tuple[int]  =  self._FixTypeInTuple( tuple(estimCurrent), int )
        self.syncConfig:     int         =  int( syncConfig)
        self.ttlSetup:       tuple[int]  =  self._FixTypeInTuple( tuple(ttlSetup), int )
        super().__init__(port,checkForValidParams)


    def GetInit(self) -> str : 
        """Builds a string that represents the Params_8480SC constructor with the \
        arguments set to the values of this class instance. 

        Returns:
            str: String that represents the Params_8480SC constructor.
        """
        return('Morelia.Parameters.Params8401HR(port=\''+self.port+'\', preamp=\''+str(self.preamp)+
               '\', ledCurrent='+str(self.ledCurrent)+', ttlPullups='+str(self.ttlPullups)+
               ', estimCurrent='+str(self.estimCurrent)+', syncConfig='+str(self.syncConfig)+
               ', ttlSetup='+str(self.ttlSetup)+')')


    def ledCurrent_CH0(self) -> int :
        """Gets the ledCurrent value for Channel 0. 

        Returns:
            int: Channel 0 ledCurrent in mA.
        """
        return(int(self.ledCurrent[0]))
    

    def ledCurrent_CH1(self) -> int :
        """Gets the ledCurrent value for Channel 1. 

        Returns:
            int: Channel 1 ledCurrent in mA.
        """
        return(int(self.ledCurrent[1]))
    

    def estimCurrent_CH0(self) -> int :
        """Gets the estimCurrent value for Channel 0.

        Returns:
            int: Channel 0 estimCurrent in percentage.
        """
        return(int(self.estimCurrent[0]))
    

    def estimCurrent_CH1(self) -> int :
        """Gets the estimCurrent value for Channel 1. 

        Returns:
            int: Channel 1 estimCurrent in percentage.
        """
        return(int(self.estimCurrent[1]))
    
  
    def _CheckParams(self) -> None :
        """Throws an exception if Params_8206HR member variable is an invalid value.

        Raises:
            Exception: The preamp must be between 0-1023.
            Exception: Led-Curent must be between 0-600.
            Exception: Estim-Current must be between 0-100.
        """
        super()._CheckParams() 

        if(self.preamp < 0 or self.preamp > 1023 ) : 
            raise Exception('The preamp must be between 0-1023.')

        for channel in self.ledCurrent : 
            if(channel < 0 or channel > 600) :
                raise Exception('Led-Curent must be between 0-600.')
            
        for channel in self.estimCurrent : 
            if(channel < 0 or channel > 100) :
                raise Exception('Estim-Current must be between 0-100.')

    
# local imports 
from Morelia.Parameters import Params

# authorship
__author__      = "Sree Kondi"
__maintainer__  = "Sree Kondi"
__credits__     = ["Sree Kondi","Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Params8274D(Params) :

    def __init__(self,
        port:  str,
        localScan : int,                
        sampleRate :  int,    
        period : int , 
        

        checkForValidParams: bool = True
        ) -> None:
        """Sets the member variables of each 8274D parameter. Checks if the arguments are \
        valid when checkForValidParams is True.  

        Args:
            port (str): Name of the COM port.
            local scan(int) : 
        """
        self.localScan:      int  =    int(localScan)
        self.sampleRate:     int  =    int(sampleRate)
        self.period:         int  =    int(period)

        super().__init__(port,checkForValidParams)


    def GetInit(self) -> str : 
        """Builds a string that represents the Params_8274D constructor with the \
        arguments set to the values of this class instance. 

        Returns:
            str: String that represents the Params_8274D constructor.
        """
        return( 'Morelia.Parameters.Params8274D('
               + 'port=\'' + self.port 
               + '\', localScan=\'' + str(self.localScan) 
               + '\', sampleRate=\'' + str(self.sampleRate)
               + '\', period=\'' + str(self.period)
               +'\')')
        
        
    def _CheckParams(self) -> None :
            """Throws an exception if Params_8206HR instance variable is an invalid value.

            Raises:
                Exception: Sample rate must be between 100-2000 Hz.
                Exception: Preamplidier gain must be 10x or 100x.
                Exception: Low-pass EEG/EMG must be between 11-500 Hz.
            """
            super()._CheckParams() 

            if(self.localScan != 0 and self.localScan != 1 ) : 
                raise Exception('Local Scan value must be 0 or 1 (0 disables, 1 enables). ')
            
            if(self.sampleRate < 0 or self.sampleRate > 3 ) : 
                raise Exception('Sample Rate must be 0, 1 , 2 or 3.')
            
            if(self.period < 0 ) : 
                raise Exception('Period must be greater than or equal to 0. ')

    

    
    

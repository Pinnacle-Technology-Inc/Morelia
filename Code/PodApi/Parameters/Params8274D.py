# local imports 
from PodApi.Parameters import Params

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
        #connectAdd : str,           
        sampleRate :  int,   
        #name : str,
        #disconnect : str,  
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
       # self.connectAdd:     str  =    str(connectAdd)
        #self.connect:       str  =    str(connect)
        self.sampleRate:     int  =    int(sampleRate)
        #self.name:           int  =    str(name)
        #self.disconnect:     int  =    str(disconnect)
        self.period:         int  =    int(period)

        super().__init__(port,checkForValidParams)


    def GetInit(self) -> str : 
        """Builds a string that represents the Params_8274D constructor with the \
        arguments set to the values of this class instance. 

        Returns:
            str: String that represents the Params_8274D constructor.
        """
        return( 'PodApi.Parameters.Params8274D('
               + 'port=\'' + self.port 
               + '\', localScan=\'' + str(self.localScan) 
               + '\', sampleRate=\'' + str(self.sampleRate)
               + '\', period=\'' + str(self.period) 
               +'\')')

    

    
    

# local imports
from Setup_PodInterface  import Setup_Interface
from Setup_PodParameters import Params_8229

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Setup_8229(Setup_Interface) : 


    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self) -> None:
        super().__init__()
        self._podParametersDict : dict[int,Params_8229] = {}   


    # ============ PUBLIC METHODS ============      ========================================================================================================================
    

    @staticmethod
    def GetDeviceName() -> str : 
        """Returns the name of the POD device.

        Returns:
            str: 8229.
        """
        return('8229')
    
    
    # ============ PRIVATE METHODS ============      ========================================================================================================================
    
    
    # ------------ DEVICE CONNECTION ------------
    
    
    # ------------ SETUP POD PARAMETERS ------------
    
    
    # ------------ DISPLAY POD PARAMETERS ------------
    
    
    # ------------ FILE HANDLING ------------
    
    
    # ------------ STREAM ------------ 


    # ============ WORKING ============      ========================================================================================================================

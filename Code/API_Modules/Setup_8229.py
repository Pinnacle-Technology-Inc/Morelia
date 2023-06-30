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

   
   # ============ GLOBAL CONSTANTS ============      ========================================================================================================================


    # overwrite from parent
    _NAME : str = '8229'
    """Class-level string containing the POD device name.
    """

    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self) -> None:
        super().__init__()
        self._podParametersDict : dict[int,Params_8229] = {}   

    # ============ PUBLIC METHODS ============      ========================================================================================================================
    
    
    # ============ PRIVATE METHODS ============      ========================================================================================================================
    
    
    # ------------ DEVICE CONNECTION ------------
    
    
    # ------------ SETUP POD PARAMETERS ------------
    
    
    # ------------ DISPLAY POD PARAMETERS ------------
    
    
    # ------------ FILE HANDLING ------------
    
    
    # ------------ STREAM ------------ 


    # ============ WORKING ============      ========================================================================================================================

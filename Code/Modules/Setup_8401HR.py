"""
Setup_8401HR provides the setup functions for an 8206-HR POD device.
"""

# enviornment imports

# local imports
from Setup_PodInterface  import Setup_Interface
from PodDevice_8401HR    import POD_8401HR 

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Setup_8401HR(Setup_Interface) : 
    
    # ============ GLOBAL CONSTANTS ============      ========================================================================================================================
    

    # overwrite from parent
    _NAME : str = '8401-HR'


    # ============ PUBLIC METHODS ============      ========================================================================================================================


    @staticmethod
    def GetDeviceName() -> str : 
        # returns the name of the POD device 
        return(Setup_8401HR._NAME)
    

    # ============ PRIVATE METHODS ============      ========================================================================================================================


    def _GetParam_onePODdevice(self, forbiddenNames: list[str]) -> dict[str,(str|int|dict)] :
        return({
            self._PORTKEY   : self._ChoosePort(forbiddenNames),
            'Sample Rate'   : Setup_Interface._AskForIntInRange('Set sample rate (Hz)', 2000, 20000),
            'Preamplifier Device'  : self._GetPreampDeviceName(),
            # 'Preamplifier Gain' : # {ABCD}
            # 'Second Stage Gain' : 
            # 'High-pass'     : 
            # 'Low-pass'      :
            # 'Bias'          :
        })

    def _GetPreampDeviceName(self) -> str : 
        # ask user for name of the preamp device 
        device = input('Set mouse/rat preamplifier: ')
        # check that a valid device name was given...
        if(not POD_8401HR.IsPreampDeviceSupported(device)) :
            # ...if not, print error and prompt again 
            print('[!] Please input a valid mouse/rat preamplifier '+str(tuple(POD_8401HR.GetSupportedPreampDevices()))+'.')
            return(self._GetPreampDeviceName())
        return(device)
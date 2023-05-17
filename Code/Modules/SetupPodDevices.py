"""
SetupPodDevices allows a user to set up and stream from any number of POD devices. The streamed data is saved to a file
"""

# enviornment imports

# local imports
from Setup_8206HR import Setup_8206HR

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class SetupPodDevices :     
    
    # ============ DUNDER METHODS ============      ========================================================================================================================

    def __init__(self, saveFile=None, podParametersDict={'8206HR':None}) :
        # initialize class instance variables
        self._setupPodDevices = { '8206HR' : Setup_8206HR() } # NOTE add supporded devices here 
        self._saveFileName = ''
        self._options = { # NOTE if you change this, be sure to update _DoOption()
            1 : 'Start streaming.',
            2 : 'Show current settings.',
            3 : 'Edit save file path.',
            4 : 'Edit POD device parameters.',
            5 : 'Connect a new POD device.',
            6 : 'Reconnect current POD devices.',
            7 : 'Generate initialization code.', 
            8 : 'Quit.'
        }
        # setup 
        self.SetupPODparameters(podParametersDict)
        # self.SetupSaveFile(saveFile)


    # ============ PUBLIC METHODS ============      ========================================================================================================================


    def SetupPODparameters(self, podParametersDict={'8206HR':None}):
        # for each type of POD device 
        for key, value in podParametersDict.items() : 
            self._setupPodDevices[key].SetupPODparameters(value)


    # ============ PRIVATE METHODS ============      ========================================================================================================================

        
    ###############################################
    # WORKING 
    ###############################################
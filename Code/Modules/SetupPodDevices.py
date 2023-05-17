"""
SetupPodDevices allows a user to set up and stream from any number of POD devices. The streamed data is saved to a file
"""

# enviornment imports
from   os           import path      as osp

# local imports
from Setup_8206HR   import Setup_8206HR

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
        self.SetupSaveFile(saveFile)


    # ============ PUBLIC METHODS ============      ========================================================================================================================


    def SetupPODparameters(self, podParametersDict={'8206HR':None}):
        # for each type of POD device 
        for key, value in podParametersDict.items() : 
            self._setupPodDevices[key].SetupPODparameters(value)


    def SetupSaveFile(self, saveFile=None):
            # initialize file name and path 
            if(saveFile == None) :
                self._saveFileName = self._GetFilePath()
                self._PrintSaveFile()

            else:
                self._saveFileName = saveFile
    
    
    # ============ PRIVATE METHODS ============      ========================================================================================================================


    # ------------ FILE HANDLING ------------


    @staticmethod
    def _BuildFileName(fileName, devName, devNum) : 
        # build file name --> path\filename_<DEVICENAME>_<DEVICE#>.ext 
        #    ex: text.txt --> test_8206-HR_1.txt
        name, ext = osp.splitext(fileName)
        fname = name+'_'+str(devName)+'_'+str(devNum)+ext   
        return(fname)


    def _PrintSaveFile(self):
        # print name  
        print('\nStreaming data will be saved to '+ str(self._saveFileName))
 

    @staticmethod
    def _CheckFileExt(f, fIsExt=True, goodExt=['.csv','.txt','.edf'], printErr=True) : 
        # get extension 
        if(not fIsExt) : name, ext = osp.splitext(f)
        else :  ext = f
        # check if extension is allowed
        if(ext not in goodExt) : 
            if(printErr) : print('[!] Filename must have' + str(goodExt) + ' extension.')
            return(False) # bad extension 
        return(True)      # good extension 


    @staticmethod
    def _GetFilePath() : 
        # ask user for path 
        path = input('\nWhere would you like to save streaming data to?\nPath: ')
        # split into path/name and extension 
        name, ext = osp.splitext(path)
        # if there is no extension , assume that a file name was not given and path ends with a directory 
        if(ext == '') : 
            # ask user for file name 
            fileName = SetupPodDevices._GetFileName()
            # add slash if path is given 
            if(name != ''): 
                # check for slash 
                if( ('/' in name) and (not name.endswith('/')) )  :
                    name = name+'/'
                elif(not name.endswith('\\')) : 
                    name = name+'\\'
            # return complete path and filename 
            return(name+fileName)
        # prompt again if bad extension is given 
        elif( not SetupPodDevices._CheckFileExt(ext)) : return(SetupPodDevices._GetFilePath())
        # path is correct
        else :
            return(path)


    @staticmethod
    def _GetFileName():
        # ask user for file name 
        inp = input('File name: ')
        # prompt again if no name given
        if(inp=='') : 
            print('[!] No filename given.')
            return(SetupPodDevices._GetFileName())
        # get parts 
        name, ext = osp.splitext(inp)
        # default to csv if no extension is given
        if(ext=='') : ext='.csv'
        # check if extension is correct 
        if( not SetupPodDevices._CheckFileExt(ext)) : return(SetupPodDevices._GetFileName())
        # return file name with extension 
        return(name+ext)
    

    
    ###############################################
    # WORKING 
    ###############################################

   
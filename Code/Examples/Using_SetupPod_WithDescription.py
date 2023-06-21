"""
Example that demonstrates how to run SetupPodDevices. 
"""
# set path to <local path>\Python-POD-API\Code\Modules
import sys, os
sys.path.insert(0, os.path.join( os.path.abspath('.'), 'Code', 'API_Modules') )

# local imports
from Setup_PodDevices import Setup_PodDevices

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

# choose which example to run 
runExample = input('\nWhat example do you want to run?: ')

# ===== EXAMPLE 1: FIRST TIME SETUP =====
if(runExample == '1'): 
    print('~~ Example 1: First Time Setup ~~')
    """
    First, this will ask you how many devices you are using. You will be asked some questions 
    to define the setup parameters for each POD device. Then, it will ask you for a path and 
    filename to save POD streaming data to. 
    """
    go = Setup_PodDevices() # create object to setup 8206HR POD devices.
    """
    After setup is complete, you will be presented with an option menu. If you want to save 
    your current setup, complete option #1 and #6. Save these outputs and use according to 
    Example 2 below. This will run until you select option #8 to quit. 
    """    
    go.Run() # start the program 
    """
    optional: you can store setup parameters as variables. 
    """
    newParams = go.GetPODparametersDict()
    newFile   = go.GetSaveFileName()
    print('Parameters: \npodParametersDict = ', newParams, '\nsaveFile = ', newFile, '\n')

# ===== EXAMPLE 2: USING INITIALIZATION OPTIONS =====
elif(runExample == '2'):
    print('~~ Example 2: Using Initialization Options ~~')
    """
    NOTE: the params and path variables are for reference only. These will likely not work 
    on your computer. Follow Example 1 to get params and path that work for you. 
    """
    # example path and file name to save streaming data to. 
    #   Note that the POD device number will be appended to the end of the filename.
    saveFile = r'C:\Users\tkelly\Desktop\TEST\test.csv'
    # example dictionary with 8206HR POD device setup parameters
    podParametersDict = { '8206-HR' : {
        1: {'Port': 'COM5 - USB EEG/EMG (COM5)', 'Sample Rate': 500, 'Preamplifier Gain': 100, 'Low-pass': {'EEG1': 40, 'EEG2': 40, 'EEG3/EMG': 40}}, 
        2: {'Port': 'COM4 - USB EEG/EMG (COM4)', 'Sample Rate': 500, 'Preamplifier Gain': 10,  'Low-pass': {'EEG1': 40, 'EEG2': 40, 'EEG3/EMG': 40}}}}
    """
    Setting the saveFile and podParametersDict parameters will satisfy the initialization steps. 
    """
    go = Setup_PodDevices(saveFile, podParametersDict) # create object to setup 8206HR POD devices

    """
    Initialization is automatically completed. You will be presented with an option menu. If you 
    want to save your current setup, complete option #1 and #6. Save these outputs and use 
    according to Example 2 below. This will run until you select option #8 to quit.  
    """
    go.Run() # start the program 
    """
    optional: you can store setup parameters as variables. 
    """    
    newParams = go.GetPODparametersDict()
    newFile   = go.GetSaveFileName()
    print('Parameters: \npodParametersDict = ', newParams, '\nsaveFile = ', newFile, '\n')

# ===== BAD INPUT =====
else:
    print('[!] There is no example', runExample)

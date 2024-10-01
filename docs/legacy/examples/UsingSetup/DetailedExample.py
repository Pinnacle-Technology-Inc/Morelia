"""
Example that demonstrates how to run SetupPodDevices. 
"""

# add directory path to code 
import Path 
Path.AddAPIpath()

# local imports
from Setup.SetupAllDevices  import SetupAll
from Morelia.Parameters      import Params8206HR

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
    go = SetupAll() # create object to setup 8206HR POD devices.
    """
    After setup is complete, you will be presented with an option menu. If you want to save 
    your current setup, complete option #1 and #6. Save these outputs and use according to 
    Example 2 below. This will run until you select option #8 to quit. 
    """    
    go.Run() # start the program 
    """
    optional: you can store setup parameters as variables. 
    """
    newParams = go.GetPODparametersInit()
    newFile   = go.GetSaveFileNames()
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
    saveFile = { '8206-HR' : r'C:\Users\tkelly\Desktop\TEST\test.csv' }
    # example dictionary with 8206HR POD device setup parameters
    podParametersDict = { '8206-HR' : { 
        1 : Params8206HR(port='COM5 - USB EEG/EMG (COM5)', sampleRate=500, preamplifierGain=100, lowPass=(40, 40, 40)) , 
        2 : Params8206HR(port='COM4 - USB EEG/EMG (COM4)', sampleRate=500, preamplifierGain=10,  lowPass=(40, 40, 40)) } }
    """
    Setting the saveFile and podParametersDict parameters will satisfy the initialization steps. 
    """
    go = SetupAll(saveFile, podParametersDict) # create object to setup 8206HR POD devices

    """
    Initialization is automatically completed. You will be presented with an option menu. If you 
    want to save your current setup, complete option #1 and #6. Save these outputs and use 
    according to Example 2 below. This will run until you select option #8 to quit.  
    """
    go.Run() # start the program 
    """
    optional: you can store setup parameters as variables. 
    """    
    newParams = go.GetPODparametersInit()
    newFile   = go.GetSaveFileNames()
    print('Parameters: \npodParametersDict = ', newParams, '\nsaveFile = ', newFile, '\n')

# ===== BAD INPUT =====
else:
    print('[!] There is no example', runExample)

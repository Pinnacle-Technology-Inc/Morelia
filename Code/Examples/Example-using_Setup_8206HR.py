"""
Example that demonstrates how to run Setup_8206HR. 
"""
# set path to <path>\Python-POD-API\Code\Modules
import sys, os
sys.path.append(os.path.join(os.path.dirname(sys.path[0]),'Modules')) 

# local imports
from Setup_8206HR import Setup_8206HR

# authorship
__author__      = "Thresa Kelly"
__email__       = "sales@pinnaclet.com"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__maintainer__  = "Thresa Kelly"
__date__        = "01/31/2023"

# choose which example to run 
runExample = input('\nWhat example do you want to run?: ')

# ===== EXAMPLE 1: FIRST TIME SETUP =====
if(runExample == '1'): 
    print('~~ Example 1: first time setup ~~')

    # create object to setup 8206HR POD devices.
    """
    First, this will ask you how many devices you are using. You will be asked some questions 
    to define the setup parameters for each POD device. Then, it will ask you for a path and 
    filename to save POD streaming data to. 
    """
    go = Setup_8206HR()

    # start the program 
    """
    After setup is complete, you will be presented with an option menu. If you want to save 
    your current setup, complete option #1 and #6. Save these outputs and use according to 
    Example 2 below. This will run until you select option #8 to quit. 
    """    
    go.Run()

# ===== EXAMPLE 2: USING INITIALIZATION OPTIONS =====
elif(runExample == '2'):
    """
    NOTE: the params and path variables are for reference only. These will likely not work 
    on your computer. Follow Example 1 to get params and path that work for you. 
    """
    print('~~ Example 2: using initialization options ~~')

    # example dictionary of 8206HR POD device setup parameters
    params = {1: {'Port': 'COM5 - USB EEG/EMG (COM5)', 'Sample Rate': 500, 'Preamplifier Gain': 100, 'Low Pass': {'EEG1': 40, 'EEG2': 40, 'EEG3/EMG': 40}}, 
              2: {'Port': 'COM4 - USB EEG/EMG (COM4)', 'Sample Rate': 500, 'Preamplifier Gain': 10,  'Low Pass': {'EEG1': 40, 'EEG2': 40, 'EEG3/EMG': 40}}}
    
    # example path and file name to save streaming data to. Note that the POD device number will be appended to the end of the filename.
    path = 'C:\\Users\\tkelly\\Desktop\\TEST\\test.csv'

    # create object to setup 8206HR POD devices
    """
    Setting the saveFile and podParametersDict parameters will satisfy the initialization steps. 
    """
    go = Setup_8206HR(saveFile=path, podParametersDict=params)

    # start the program 
    go.Run()

else:
    print('[!] There is no example', runExample)
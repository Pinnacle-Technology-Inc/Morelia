"""
Setup_8206HR allows a user to set up and stream from any number of 8206HR POD devices. The streamed data is saved to a file. 
"""

# enviornment imports
import os
import texttable
import threading 
import time 
import pyedflib  
# local imports
from SerialCommunication    import COM_io
from PodDevice_8206HR       import POD_8206HR

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__email__       = "sales@pinnaclet.com"
__date__        = "02/21/2023"

class Setup_8206HR : 


    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self, saveFile=None, podParametersDict=None) :
        # initialize class instance variables
        self._podDevices = {}
        self._podParametersDict = {}
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


    def __del__(self):
        # delete all POD objects 
        self._DisconnectAllPODdevices


    # ============ PUBLIC METHODS ============      ========================================================================================================================


    def SetupPODparameters(self, podParametersDict=None):
        # get dictionary of POD device parameters
        if(podParametersDict==None):
            self._SetParam_allPODdevices()  # get setup parameters for all POD devices
            self._ValidateParams()          # display parameters and allow user to edit them
        else:
            self._podParametersDict = podParametersDict
        # connect and initialize all POD devices
        self._ConnectAllPODdevices()


    def SetupSaveFile(self, saveFile=None):
        # initialize file name and path 
        if(saveFile == None) :
            self._saveFileName = self._GetFilePath()
            self._PrintSaveFile()

        else:
            self._saveFileName = saveFile


    def Run(self) :
        # init looping condition 
        choice = 0
        quit = list(self._options.keys())[list(self._options.values()).index('Quit.')] # abstracted way to get dict key for 'Quit.'
        # keep prompting user until user wants to quit
        while(choice != quit) :
            self._PrintOptions()
            choice = self._AskOption()
            self._DoOption(choice)


    # ============ PRIVATE METHODS ============      ========================================================================================================================

   
    # ------------ DEVICES ------------


    @staticmethod
    def _SetNumberOfDevices() : 
        try : 
            # request user imput
            n = int(input('\nHow many POD devices do you want to use?: '))
            # number must be positive
            if(n<=0):
                print('[!] Number must be greater than zero.')
                return(Setup_8206HR._SetNumberOfDevices())
            # return number of POD devices 
            return(n)
        except : 
            # print error and start over
            print('[!] Please enter an integer number.')
            return(Setup_8206HR._SetNumberOfDevices())
    

    def _DisconnectAllPODdevices(self) :
        for k in list(self._podDevices.keys()) : 
            pod = self._podDevices.pop(k)
            del pod 


    def _ConnectAllPODdevices(self) : 
        # delete existing 
        self._DisconnectAllPODdevices()
        # connect new devices
        print('\nConnecting POD devices...')
        # setup each POD device
        for key,val in self._podParametersDict.items():
           self._ConnectPODdevice(key,val)
                

    def _ConnectPODdevice(self, deviceNum, deviceParams) : 
        failed = True 
        try : 
            # get port name 
            port = deviceParams['Port'].split(' ')[0] # isolate COM# from rest of string
            # create POD device 
            self._podDevices[deviceNum] = POD_8206HR(port=port, preampGain=deviceParams['Preamplifier Gain'])
            # test if connection is successful
            if(self._TestDeviceConnection(self._podDevices[deviceNum])):
                # write setup parameters
                self._podDevices[deviceNum].WriteRead('SET SAMPLE RATE', deviceParams['Sample Rate'])
                self._podDevices[deviceNum].WriteRead('SET LOWPASS', (0, deviceParams['Low Pass']['EEG1']))
                self._podDevices[deviceNum].WriteRead('SET LOWPASS', (1, deviceParams['Low Pass']['EEG2']))
                self._podDevices[deviceNum].WriteRead('SET LOWPASS', (2, deviceParams['Low Pass']['EEG3/EMG']))   
                failed = False
        except : pass

        # check if connection failed 
        if(failed) :
            print('Failed to connect POD device #'+str(deviceNum)+' to '+port+'.')
        else :
            print('Successfully connected POD device #'+str(deviceNum)+' to '+port+'.')
        # return True when connection successful, false otherwise
        return(not failed)


    def _AddPODdevice(self):
        nextNum = max(self._podParametersDict.keys())+1
        self._PrintDeviceNumber(nextNum)
        self._podParametersDict[nextNum] = self._GetParam_onePODdevice(self._GetForbiddenNames())


    # ------------ SETUP POD PARAMETERS ------------
    

    def _SetParam_allPODdevices(self) :
        # get the number of devices 
        numDevices = self._SetNumberOfDevices()
        # initialize 
        portNames = [None] * numDevices
        podDict = {}
        # get information for each POD device 
        for i in range(numDevices) : 
            # current index 
            self._PrintDeviceNumber(i+1)
            # get parameters
            onePodDict = Setup_8206HR._GetParam_onePODdevice(portNames)
            # update lists 
            portNames[i] = onePodDict['Port']
            podDict[i+1] = onePodDict
        # save dict containing information to setup all POD devices
        self._podParametersDict = podDict


    @staticmethod
    def _GetParam_onePODdevice(forbiddenNames) : 
        return({
                'Port'              : Setup_8206HR._ChoosePort(forbiddenNames),
                'Sample Rate'       : Setup_8206HR._ChooseSampleRate(),
                'Preamplifier Gain' : Setup_8206HR._ChoosePreampGain(),
                'Low Pass'          : Setup_8206HR._ChooseLowpass()
            })
        
    
    @staticmethod
    def _ChoosePort(forbidden=[]) : 
        # get ports
        portList = Setup_8206HR._GetPortsList(forbidden)
        print('Available COM Ports:', portList)
        # request port from user
        choice = input('Select port: COM')
        # choice cannot be an empty string
        if(choice == ''):
            print('[!] Please choose a COM port.')
            return(Setup_8206HR._ChoosePort(forbidden))
        else:
            # search for port in list
            for port in portList:
                if port.startswith('COM'+choice):
                    return(port)
            # if return condition not reached...
            print('[!] COM'+choice+' does not exist. Try again.')
            return(Setup_8206HR._ChoosePort(forbidden))


    @staticmethod
    def _GetPortsList(forbidden=[]) : 
        # get port list 
        portListAll = COM_io.GetCOMportsList()
        if(forbidden):
            # remove forbidden ports
            portList = [x for x in portListAll if x not in forbidden]
        else:
            portList = portListAll
        # check if the list is empty 
        if (len(portList) == 0):
            # print error and keep trying to get ports
            print('[!] No COM ports in use. Please plug in POD device.')
            while(len(portList) == 0) : 
                portListAll = COM_io.GetCOMportsList()
                portList = [x for x in portListAll if x not in forbidden]
        # return port
        return(portList)
    

    @staticmethod
    def _ChooseSampleRate():
        try : 
            # get sample rate from user 
            sampleRate = int(input('Set sample rate (Hz): '))
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8206HR._ChooseSampleRate())
        # check for valid input
        if(sampleRate<100 or sampleRate>2000) : 
            print('[!] Sample rate must be between 100-2000.')
            return(Setup_8206HR._ChooseSampleRate())
        # return sample rate
        return(sampleRate)
       

    @staticmethod
    def _ChoosePreampGain():
        try:
            # get gain from user 
            gain = int(input('Set preamplifier gain: '))
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8206HR._ChoosePreampGain())
        # check for valid input 
        if(gain != 10 and gain != 100):
            # prompt again 
            print('[!] Preamplifier gain must be 10 or 100.')
            return(Setup_8206HR._ChoosePreampGain())
        # return preamplifier gain 
        return(gain)


    @staticmethod
    def _ChooseLowpass():
        # get lowpass for all EEG
        return({
            'EEG1'      : Setup_8206HR._ChooseLowpassForEEG('EEG1'),
            'EEG2'      : Setup_8206HR._ChooseLowpassForEEG('EEG2'),
            'EEG3/EMG'  : Setup_8206HR._ChooseLowpassForEEG('EEG3/EMG'),
        })


    @staticmethod
    def _ChooseLowpassForEEG(eeg):
        try : 
            # get lowpass from user 
            lowpass = int(input('Set lowpass (Hz) for '+str(eeg)+': '))
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8206HR._ChooseLowpassForEEG(eeg))
        # check for valid input
        if(lowpass<11 or lowpass>500) : 
            print('[!] Sample rate must be between 11-500 Hz.')
            return(Setup_8206HR._ChooseLowpassForEEG(eeg))
        # return lowpass
        return(lowpass)


    # ------------ EDIT POD PARAMETERS ------------
    

    def _ValidateParams(self) : 
        # display all pod devices and parameters
        self._DisplayPODdeviceParameters()
        # ask if params are good or not
        validParams = Setup_8206HR._AskYN(question='Are the POD device parameters correct?')
        # edit if the parameters are not correct 
        if(not validParams) : 
            self._EditParams()
            self._ValidateParams()


    def _EditParams(self) :
        # chose device # to edit
        editThis = self._SelectPODdeviceFromDictToEdit()
        # get all port names except for device# to be edited
        forbiddenNames = self._GetForbiddenNames(exclude=self._podParametersDict[editThis]['Port'])
        # edit device
        self._PrintDeviceNumber(editThis)
        self._podParametersDict[editThis] = Setup_8206HR._GetParam_onePODdevice(forbiddenNames)


    def _SelectPODdeviceFromDictToEdit(self):
        try:
            # get pod device number from user 
            podKey = int(input('Edit POD Device #: '))
        except : 
            # print error and start over
            print('[!] Please enter an integer number.')
            return(self._SelectPODdeviceFromDictToEdit())

        # check is pod device exists
        keys = self._podParametersDict.keys()
        if(podKey not in keys) : 
            print('[!] Invalid POD device number. Please try again.')
            return(self._SelectPODdeviceFromDictToEdit())
        else:
            # return the pod device number
            return(podKey)


    def _GetForbiddenNames(self, exclude=None):
        if(exclude == None) : 
            portNames = [x['Port'] for x in self._podParametersDict.values()]
        else :
            portNames = [x['Port'] for x in self._podParametersDict.values() if exclude != x['Port']]
        return(portNames)


    # ------------ DISPLAY POD PARAMETERS ------------


    @staticmethod
    def _PrintDeviceNumber(num):
        print('\n-- Device #'+str(num)+' --\n')


    def _PrintPODdeviceParamDict(self):
        print('\nDictionary of current POD parameter set:\n'+str(self._podParametersDict))


    def _DisplayPODdeviceParameters(self) : 
        # print title 
        print('\nParameters for all POD Devices:')
        # setup table 
        tab = texttable.Texttable()
        # write column names
        tab.header(['Device #','Port','Sample Rate (Hz)', 'Preamplifier Gain', 'EEG1 Low Pass (Hz)','EEG2 Low Pass (Hz)','EEG3/EMG Low Pass (Hz)'])
        # write rows
        for key,val in self._podParametersDict.items() :
            tab.add_row([key, val['Port'], val['Sample Rate'], val['Preamplifier Gain'], val['Low Pass']['EEG1'], val['Low Pass']['EEG2'], val['Low Pass']['EEG3/EMG'],])
        # show table 
        print(tab.draw())
        
    
    # ------------ FILE HANDLING ------------


    def _PrintSaveFile(self):
        print('\nStreaming data will be saved to '+self._saveFileName)
 

    @staticmethod
    def _CheckFileExt(f, fIsExt=True, goodExt=['.csv','.txt','.edf'], printErr=True) : 
        # get extension 
        if(not fIsExt) : name, ext = os.path.splitext(f)
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
        name, ext = os.path.splitext(path)

        # if there is no extension , assume that a file name was not given and path ends with a directory 
        if(ext == '') : 
            # ask user for file name 
            fileName = Setup_8206HR._GetFileName()

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
        elif( not Setup_8206HR._CheckFileExt(ext)) : return(Setup_8206HR._GetFilePath())

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
            return(Setup_8206HR._GetFileName())
        # get parts 
        name, ext = os.path.splitext(inp)
        # default to csv if no extension is given
        if(ext=='') : ext='.csv'
        # check if extension is correct 
        if( not Setup_8206HR._CheckFileExt(ext)) : return(Setup_8206HR._GetFileName())
        # return file name with extension 
        return(name+ext)


    def _OpenSaveFile(self, devNum) : 
        # build file name --> path\filename_<DEVICE#>.ext
        name, ext = os.path.splitext(self._saveFileName)
        fname = name+'_'+str(devNum)+ext    

        f = None
        if(ext=='.csv' or ext=='.txt') :
            # open file to write to 
            f = open(fname, 'w')
            # write column names to header
            f.write('time,TTL,ch0,ch1,ch2\n')
        
        elif(ext=='.edf') : 
            pass

        return(f)


    @staticmethod
    def _WriteDataToFile(t, data, file):
        # get useful data in list 
        data = [t, data['TTL'], data['Ch0'], data['Ch1'], data['Ch2']]
        # convert data into comma separated string
        line = ','.join(str(x) for x in data) + '\n'
        # write data to file 
        file.write(line)


    # ------------ STREAM ------------ 


    def _AskToStopStream(self):
        # get any input from user 
        input('\nPress Enter to stop streaming:')
        # tell devices to stop streaming 
        for pod in self._podDevices.values() : 
            pod.WritePacket(cmd='STREAM', payload=0)
        print('Finishing up...')


    @staticmethod
    def _StreamUntilStop(pod, file, sampleRate):
        # initialization
        t = 0   # current time 
        dt = 1.0 / sampleRate   # time to take each sample 
        stopAt = pod.GetPODpacket(cmd='STREAM', payload=0)  # packet to mark stop streaming 
        # start streaming from device  
        pod.WriteRead(cmd='STREAM', payload=1)
        while(True) : 
            r = pod.ReadPODpacket() # read from POD device 
            if(r == stopAt) : break # stop looping when stop stream command is read 
            Setup_8206HR._WriteDataToFile(t, pod.TranslatePODpacket(r), file)   # write what is read to file 
            t = round(t+dt, 6)  # increment time, rounding to 6 decimal places


    def _StreamThreading(self) :
        # create save files for pod devices
        podFiles = {devNum: self._OpenSaveFile(devNum) for devNum in self._podDevices.keys()}
        # make threads for reading 
        readThreads = {
            # create thread to _StreamUntilStop() to dictionary entry devNum
            devNum : threading.Thread(
                    target = Setup_8206HR._StreamUntilStop, 
                    args = ( pod, file, params['Sample Rate'] )
                )
            # for each device 
            for devNum,params,pod,file in 
                zip(
                    self._podParametersDict.keys(),     # devNum
                    self._podParametersDict.values(),   # params
                    self._podDevices.values(),          # pod
                    podFiles.values()                   # file
                ) 
        }
        # make thread for user input 
        userThread  = threading.Thread(target=self._AskToStopStream)
        # start streaming 
        for t in readThreads.values() : t.start()
        userThread.start()
        # join all threads --> waits until all threads are finished before continuing 
        userThread.join()
        for t in readThreads.values() : t.join()
        # close all files 
        for file in podFiles.values() : file.close()
        print('Save complete!')

    def _Stream(self) : 
        # check for good connection 
        if(not self._TestDeviceConnection_All()): 
            print('Could not stream.')
        # start streaming from all devices 
        else:
            self._TimeFunc(self._StreamThreading)


    # ------------ OPTIONS ------------


    def _PrintOptions(self):
        print('\nOptions:')
        for key,val in self._options.items() : 
            print(str(key)+'. '+val)
    

    def _AskOption(self):
        try:
            # get option number from user 
            choice = int(input('\nWhat would you like to do?: '))
        except : 
            # print error and ask again
            print('[!] Please enter an integer number.')
            return(self._AskOption())
        # choice must be an available option 
        if(not choice in self._options.keys()):
            print('[!] Invalid Selection. Please choose an available option.')
            return(self._AskOption())
        # return valid choice
        return(choice)


    def _DoOption(self, choice) : 
        # Start Streaming.
        if  (choice == 1):  
            self._Stream()
        # Show current settings.
        elif(choice == 2):  
            self._DisplayPODdeviceParameters()
            self._PrintSaveFile()
        # Edit save file path.
        elif(choice == 3):  
            self._saveFileName = self._GetFilePath()
            self._PrintSaveFile()
        # Edit POD device parameters.
        elif(choice == 4):  
            self._DisplayPODdeviceParameters()
            self._EditParams()
            self._ValidateParams()
            self._ConnectAllPODdevices()
        # Connect a new POD device.
        elif(choice == 5):  
            self._AddPODdevice()
            self._ValidateParams()
            self._ConnectAllPODdevices()
        # Reconnect current POD devices.
        elif(choice == 6):  
            self._ConnectAllPODdevices()
        # Generate initialization code.
        elif(choice == 7):  
            self._PrintInitCode()
        # Quit.
        else:               
            print('\nQuitting...\n')


    # ------------ HELPER ------------


    @staticmethod
    def _AskYN(question) : 
        response = input(str(question)+' (y/n): ').upper() 
        if(response=='Y' or response=='YES'):
            return(True)
        elif(response=='N' or response=='NO'):
            return(False)
        else:
            print('[!] Please enter \'y\' or \'n\'.')
            return(Setup_8206HR._AskYN(question))


    @staticmethod
    def _TimeFunc(func) : 
        ti = time.time() # start time 
        func() # run function 
        dt = round(time.time()-ti,3) # calculate time difference
        print('\nExecution time:', str(dt), 'sec') # print and return execultion time 
        return(dt)


    @staticmethod
    def _TestDeviceConnection(pod):
        # returns True when connection is successful, false otherwise
        try:
            w = pod.WritePacket(cmd='PING')
            r = pod.ReadPODpacket()
        except:     return(False)
        # check that read matches ping write
        if(w==r):   return(True)
        else:       return(False)


    def _TestDeviceConnection_All(self) :
        allGood = True
        for key,pod in self._podDevices.items(): 
            # test connection of each pod device
            if(not self._TestDeviceConnection(pod)) : 
                # write newline for first bad connection 
                if(allGood==True) : print('') 
                # print error message
                print('Connection issue with POD device #'+str(key)+'.')
                # flag that a connection failed
                allGood = False 
        # return True when all connections are successful, false otherwise
        return(allGood)


    def _PrintInitCode(self):
        print(
            '\n' + 
            'saveFile = r\'' + str(self._saveFileName) + '\'\n' + 
            'podParametersDict = ' + str(self._podParametersDict)  + '\n' + 
            'go = Setup_8206HR(saveFile, podParametersDict)'  + '\n' + 
            'go.Run()'
        )
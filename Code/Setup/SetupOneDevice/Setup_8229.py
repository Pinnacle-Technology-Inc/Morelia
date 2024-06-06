# enviornment imports
from texttable  import Texttable
from io         import IOBase
from threading  import Thread
import time

# local imports
from Setup.SetupOneDevice   import SetupInterface
from Setup.Inputs           import UserInput
from Morelia.Packets        import PacketStandard
from Morelia.Devices        import Pod8229
from Morelia.Parameters     import Params8229

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"


class Setup8229(SetupInterface) : 
    """Setup_8229 provides the setup functions for an 8229 POD device.

    Attributes:
        _streamMode (bool): True when the user wants to stream data from an 8229 POD \
            device, False otherwise.
    """

    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self) -> None:
        """Initializes the class instance variables.
        """
        super().__init__()
        self._podParametersDict : dict[int,Params8229] = {} # correct Param type
        self._streamMode : bool = False


    # ============ PUBLIC METHODS ============      ========================================================================================================================
    

    @staticmethod
    def GetDeviceName() -> str : 
        """Returns the name of the POD device.

        Returns:
            str: 8229.
        """
        return('8229')
    

    @staticmethod
    def GetSupportedFileExtensions() -> list[str] : 
        """Returns a list containing valid file extensions. 

        Returns:
            list[str]: List of string file extensions.
        """
        return(['.csv','.txt'])
    
    
    def StopStream(self) -> None: 
        """Update the state flag to signal to stop streaming data.
        """
        self._streamMode = False

        
    # ============ PRIVATE METHODS ============      ========================================================================================================================
    
    
    # ------------ DEVICE CONNECTION ------------
    

    def _ConnectPODdevice(self, deviceNum: int, deviceParams: Params8229) -> bool : 
        """Creates a 8229 POD device object and write the setup parameters to it. 

        Args:
            deviceNum (int): Integer of the device's number.
            deviceParams (Params_8229): Device parameters.

        Returns:
            bool: True if connection was successful, false otherwise.
        """
        # initialize flag 
        success = False 
        # get port name 
        port = deviceParams.port.split(' ')[0] # isolate COM# from rest of string
        try : 
            # create POD device 
            pod = Pod8229(port=port)
            # test if connection is successful
            if(not self._TestDeviceConnection(pod)): raise Exception('Could not connect to POD device.')
            # set current computer time 
            pod.WriteRead('SET TIME', pod.GetCurrentTime())
            # set mode to PC control and stop motor
            pod.WriteRead('SET MODE', 1)
            pod.WriteRead('SET MOTOR STATE', 0)
            # write setup parameters
            pod.WriteRead('SET ID',                 deviceParams.systemID)
            pod.WriteRead('SET MOTOR DIRECTION',    deviceParams.motorDirection)
            pod.WriteRead('SET MOTOR SPEED',        deviceParams.motorSpeed)
            pod.WriteRead('SET RANDOM REVERSE',     deviceParams.randomReverse)
            # write conditional params 
            if(deviceParams.randomReverse) : 
                pod.WriteRead('SET REVERSE PARAMS', (deviceParams.reverseBaseTime, deviceParams.reverseVarTime) )
            if(deviceParams.mode == 2):
                for day, hours in deviceParams.schedule.items() :
                    pod.WriteRead('SET DAY SCHEDULE', Pod8229.BuildSetDayScheduleArgument(day, hours, deviceParams.motorSpeed))
            # set mode last
            pod.WriteRead('SET MODE',               deviceParams.mode)
            # successful write if no exceptions raised 
            self._podDevices[deviceNum] = pod
            success = True
            print('Successfully connected device #'+str(deviceNum)+' to '+port+'.')
        except Exception as e :
            self._podDevices[deviceNum] = False # fill entry with bad value
            print('[!] Failed to connect device #'+str(deviceNum)+' to '+port+': '+str(e))
        # return True when connection successful, false otherwise
        return(success)
    
    
    # ------------ SETUP POD PARAMETERS ------------
    
    
    def _GetParam_onePODdevice(self, forbiddenNames: list[str] = []) -> Params8229 :
        """Asks the user to input all the device parameters. 

        Args:
            forbiddenNames (list[str], optional): List of port names already used \
                by other devices. Defaults to [].

        Returns:
            Params_8229: Device parameters.
        """
        MAX = 0xFFFF # max value for U16 (xFFFF = 65535 in decimal)
        # basic params 
        port            = self._ChoosePort(forbiddenNames)
        systemID        = UserInput.AskForIntInRange('Set system ID', 0, 999)
        motorDirection  = UserInput.AskForIntInRange('Set motor direction (0 for clockwise and 1 for counterclockwise)', 0, 1)
        motorSpeed      = UserInput.AskForIntInRange('Set motor speed (0-100%)', 0,100)
        # ask for addittional params if allowing random reverse 
        randomReverse = UserInput.AskYN('Enable random reverse?')
        if(randomReverse) : 
            reverseBaseTime = UserInput.AskForIntInRange('Set reverse base time (sec)', 0, MAX)
            reverseVarTime  = UserInput.AskForIntInRange('Set reverse variable time (sec)', 0, MAX)
        else :
            reverseBaseTime = None
            reverseVarTime  = None
        # set schedule if using schedule mode 
        mode = UserInput.AskForIntInRange('Set system mode (0 = Manual, 1 = PC Control, 2 = Internal Schedule)',0,2)
        if(mode == 2):
            schedule = self._GetScheduleForWeek()        
        else:
            schedule = None
        # make param object and return 
        return(Params8229(port=port, systemID=systemID, motorDirection=motorDirection, motorSpeed=motorSpeed, 
                           randomReverse=randomReverse, reverseBaseTime=reverseBaseTime, reverseVarTime=reverseVarTime, 
                           mode=mode, schedule=schedule))
    

    @staticmethod
    def _GetScheduleForWeek() -> dict[str, tuple[int]]: 
        """Asks the user to input if the motor is on/off for each hour of each \
            day of the week. 

        Returns:
            dict[str, tuple[int]]: Dictionary with the schedule. The keys are the \
                days of the week (Sunday, Monday, ...). The values are a tuple of 24 \
                items for each hour; the items are 1 if the motor is on or 0 if the \
                motor is off
        """
        schedule: dict[str, tuple[int]] = {}
        # for each day in the week...
        print('For each hour, enter \'y\' or \'1\' if the motor should be on and \'n\' or \'0\' if the motor should be off.')
        for day in Params8229.week : 
            print('Set set motor schedule for '+day+':')
            # ... for each hour... get the motor on/off status 
            schedule[day] = tuple( [UserInput.AskYN('\tHour '+str(hr), append=': ') for hr in range(Params8229.hoursPerDay)] )
        return(schedule)

    
    # ------------ DISPLAY POD PARAMETERS ------------
    
    
    def _GetPODdeviceParameterTable(self) -> Texttable : 
        """Builds a table containing the parameters for all POD devices.

        Returns:
            Texttable: Table containing all parameters.
        """
        # setup table 
        tab = Texttable(180)
        # write column names
        tab.header( ['Device #','Port','Motor Direction','Motor Speed',
                     'Random Reverse','Random Reverse Time (s)','Mode','Schedule'] )
        # write rows
        for key,val in self._podParametersDict.items() :
            # build row
            row = [ key, val.port ]
            match val.motorDirection : 
                case 0 : row.append('Clockwise')
                case _ : row.append('Counterclockwise') # 1
            row.append(str(val.motorSpeed)+'%')
            row.append(str(val.randomReverse))
            match val.randomReverse : 
                case True : row.append('Base: '+str(val.reverseBaseTime)+'\nVariable: '+str(val.reverseVarTime))
                case    _ : row.append('None')
            match val.mode :
                case 0 : 
                    row.append('Manual')
                    row.append('None')
                case 1 : 
                    row.append('PC Control')
                    row.append('None')
                case _ : # 2 
                    row.append('Internal Schedule')
                    row.append(val.schedule)
            # add row to table 
            tab.add_row(row)
        # return complete texttable 
        return(tab)
    
    
    # ------------ FILE HANDLING ------------
    

    def _OpenSaveFile_EDF(self, fname: str, devNum: int) :
        """EDF files are not supported for 8229 POD devices. Overwrites the \
        parent's method, which would open an EDF file and write the header.

        Args:
            fname (str): String filename. Not used.
            devNum (int): Integer device number. Not used.

        Raises:
            Exception: EDF filetype is not supported for 8229 POD devices.
        """
        raise Exception('[!] EDF filetype is not supported for 8229 POD devices.')
    

    def _OpenSaveFile_TXT(self, fname: str) -> IOBase : 
        """Opens a text file and writes the column names. Writes the current date/time \
        at the top of the txt file.

        Args:
            fname (str): String filename. 

        Returns:
            IOBase: Opened file.
        """
        # open file and write column names 
        f = open(fname, 'w')
        # write time
        f.write( self._GetTimeHeader_forTXT() ) 
        # columns names
        f.write('\nTime (s),Command Number,Payload\n')
        return(f)
    

    # ------------ STREAM ------------ 


    def _StreamThreading(self) -> dict[int,Thread] :
        """Opens a save file, then creates a thread for each device to stream and write \
        data from. 

        Returns:
            dict[int,Thread]: Dictionary with keys as the device number and values as the \
                started Thread.
        """
        # set state 
        self._streamMode = True
        # create save files for pod devices
        podFiles = {devNum: self._OpenSaveFile(devNum) for devNum in self._podDevices.keys()}
        # make threads for reading 
        readThreads = {
            # create thread to _StreamUntilStop() to dictionary entry devNum
            devNum : Thread(
                    target = self._StreamUntilStop, 
                    args   = (pod, file))
            # for each device 
            for devNum,pod,file in 
                zip(
                    self._podParametersDict.keys(),     # devNum
                    self._podDevices.values(),          # pod
                    podFiles.values() )                 # file
        }
        for t in readThreads.values() : 
            # start streaming (program will continue until .join() or streaming ends)
            t.start()
        return(readThreads)
    

    def _StreamUntilStop(self, pod: Pod8229, file: IOBase) -> None :
        """Saves a log of all packets recieved from the 8229 POD device until the user decides \
        to stop streaming.

        Args:
            pod (POD_8229): POD device to read from. 
            file (IOBase): Opened text file to save data to.
        """
        # initialize
        currentTime : float = 0.0
        t : float = (round(time.time(),9)) # initial time (sec)          
        # start waiting for data   
        while(self._streamMode) : 
            try : 
                # attempt to read packet.         vvv An exception will occur HERE if no data can be read 
                read: PacketStandard = pod.ReadPODpacket(timeout_sec=1)
                # update time by adding (dt = tf - ti)
                currentTime += (round(time.time(),9)) - t 
                # build line to write 
                data = [str(currentTime), str(read.CommandNumber())]
                if(read.HasPayload()) : data.append(str(read.Payload()))
                else :                  data.append('None')
                # write to file 
                file.write(','.join(data) + '\n')
                # update initial time for next loop 
                t = (round(time.time(),9)) # initial time (sec)
            except : 
                continue # keep looping 
            # end while 
        # streaming done
        file.close()


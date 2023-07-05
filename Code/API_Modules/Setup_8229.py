# local imports
from Setup_PodInterface  import Setup_Interface
from Setup_PodParameters import Params_8229
from GetUserInput        import UserInput
from PodDevice_8229      import POD_8229

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
    

    def _ConnectPODdevice(self, deviceNum: int, deviceParams: Params_8229) -> bool : 
        """Creates a 8992 POD device object and write the setup parameters to it. 

        Args:
            deviceNum (int): Integer of the device's number.
            deviceParams (Params_8229): Device parameters.

        Returns:
            bool: True if connection was successful, false otherwise.
        """
        success = False 
        # get port name 
        port = deviceParams.port.split(' ')[0] # isolate COM# from rest of string
        try : 
            # create POD device 
            self._podDevices[deviceNum] = POD_8229(port=port)
            # test if connection is successful
            if(self._TestDeviceConnection(self._podDevices[deviceNum])):
                # write setup parameters
                self._podDevices[deviceNum].WriteRead('SET ID',                 deviceParams.systemID)
                self._podDevices[deviceNum].WriteRead('SET MOTOR DIRECTION',    deviceParams.motorDirection)
                self._podDevices[deviceNum].WriteRead('SET MOTOR SPEED',        deviceParams.motorSpeed)
                self._podDevices[deviceNum].WriteRead('SET RANDOM REVERSE',     deviceParams.randomReverse)
                self._podDevices[deviceNum].WriteRead('SET MODE',               deviceParams.mode)
                # write conditional params 
                if(deviceParams.randomReverse) : 
                    self._podDevices[deviceNum].WriteRead('SET REVERSE PARAMS', (deviceParams.reverseBaseTime, deviceParams.reverseVarTime) )
                if(deviceParams.mode == 2):
                    for day, hours in deviceParams.schedule.items() :
                        self._podDevices[deviceNum].WriteRead('SET DAY SCHEDULE', POD_8229.BuildSetDayScheduleArgument(day, hours, deviceParams.motorSpeed))
                # successful write if no exceptions raised 
                success = True
                print('Successfully connected device #'+str(deviceNum)+' to '+port+'.')
        except Exception as e :
            self._podDevices[deviceNum] = 0 # fill entry with bad value
            print('[!] Failed to connect device #'+str(deviceNum)+' to '+port+': '+str(e))
        # return True when connection successful, false otherwise
        return(success)
    
    
    # ------------ SETUP POD PARAMETERS ------------
    
    
    def _GetParam_onePODdevice(self, forbiddenNames: list[str] = []) -> Params_8229 :
        MAX = 0xFFFF # max value for U16 (xFFFF = 65535 in decimal)
        # basic params 
        port            = self._ChoosePort(forbiddenNames)
        systemID        = UserInput.AskForIntInRange('Set system ID', 0, MAX)
        motorDirection  = UserInput.AskForIntInRange('Set motor direction (0 for clockwise and 1 for counterclockwise)', 0, 1)
        motorSpeed      = UserInput.AskForIntInRange('Set motor speed (0-100%)', 0,100)
        # ask for addittional params if allowing random reverse 
        randomReverse = UserInput.AskYN('Enable random reverse?'),
        if(randomReverse) : 
            reverseBaseTime = UserInput.AskForIntInRange('Set reverse base time (sec)', 0, MAX)
            reverseVarTime  = UserInput.AskForIntInRange('Set reverse variable time (sec)', 0, MAX)
        else:
            reverseBaseTime = 0
            reverseVarTime  = 0
        # set schedule if using schedule mode 
        mode = UserInput.AskForIntInRange('Set system mode (0 = Manual, 1 = PC Control, 2 = Internal Schedule)',0,2)
        if(mode == 2):
            schedule = self._GetScheduleForWeek()        
        else:
            schedule = {}
        # make param object and return 
        return(Params_8229(port=port, systemID=systemID, motorDirection=motorDirection, motorSpeed=motorSpeed, 
                           randomReverse=randomReverse, reverseBaseTime=reverseBaseTime, reverseVarTime=reverseVarTime, 
                           mode=mode, schedule=schedule))
    

    @staticmethod
    def _GetScheduleForWeek() -> dict[str, tuple[int]]: 
        schedule: dict[str, tuple[int]] = {}
        # for each day in the week...
        print('For each hour, enter \'y\' or \'1\' if the motor should be on and \'n\' or \'0\' if the motor should be off.')
        for day in Params_8229.week : 
            print('Set set motor schedule for '+day+':')
            # ... for each hour... get the motor on/off status 
            schedule[day] = tuple( [UserInput.AskYN('\tHour '+str(hr), append=': ') for hr in range(Params_8229.hoursPerDay)] )
        return(schedule)

    
    # ------------ DISPLAY POD PARAMETERS ------------
    
    
    # ------------ FILE HANDLING ------------
    
    
    # ------------ STREAM ------------ 


    # ============ WORKING ============      ========================================================================================================================

# local imports
from Setup_PodInterface  import Setup_Interface
from Setup_PodParameters import Params_8229
from GetUserInput        import UserInput

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
        week = ('Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday')
        for day in week : 
            print('Set set motor schedule for '+day+':')
            # ...for each hour...
            hours = [0] * 24
            for hr in range(24) : 
                # ...get the motor on/off status 
                hours[hr] = UserInput.AskYN('\tHour '+str(hr), append=': ')
            # save dict entry 
            schedule[day] = tuple(hours)
        return(schedule)


    # ------------ DISPLAY POD PARAMETERS ------------
    
    
    # ------------ FILE HANDLING ------------
    
    
    # ------------ STREAM ------------ 


    # ============ WORKING ============      ========================================================================================================================


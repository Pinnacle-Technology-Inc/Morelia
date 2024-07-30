# enviornment imports
import copy

# local imports 
from Morelia.Parameters import Params

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Params8229(Params) :
    """Container class that stores parameters for an 8229 POD device.

    Attributes:
        port (str): Name of the COM port.
        systemID (int): ID of this 8229 POD system. Must be a positive integer. 
        motorDirection (bool): False for clockwise and true for counterclockwise.
        motorSpeed (int): Motor speed as a percentage 0-100%.
        randomReverse (bool): True to enable random reverse, False otherwise. The random reverse time will \
            be reverseBaseTime + random value in reverseVarTime range. 
        reverseBaseTime (int): Base time for a random reverse in seconds. Must be a positive integer.
        reverseVarTime (int): Variable time for a random reverse in seconds. Must be a positive integer.
        mode (int): System mode; 0 = Manual, 1 = PC Control, and 2 = Internal Schedule.
        schedule (dict[str, tuple[int]]): Schedule for a week. The keys are the weekdays (Sunday-Saturday). \
            The values are a tuple of 24 bools that are either 1 for motor on or 0 for motor off
    """

    week: tuple[str] = ('Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday')
    """Tuple containing strings of the 7 days of the week."""

    hoursPerDay: int = 24
    """Integer storing the number of hours in a day."""

    def __init__(self, 
                 port:              str, 
                 systemID:          int, 
                 motorDirection:    bool, 
                 motorSpeed:        int, 
                 randomReverse:     bool, 
                 mode:              int, 
                 reverseBaseTime:   int = None,
                 reverseVarTime:    int = None,
                 schedule:          dict[str, tuple[bool]] = None, 
                 checkForValidParams: bool = True
                ) -> None:
        """Sets the instance variables of each 8229 parameter. Checks if the arguments are \
        valid when checkForValidParams is True.  

        Args:
            port (str): Name of the COM port.
            systemID (int): ID of this 8229 POD system. Must be a positive integer. 
            motorDirection (bool): False for clockwise and true for counterclockwise.
            motorSpeed (int): Motor speed as a percentage 0-100%.
            randomReverse (bool): True to enable random reverse, False otherwise. The random reverse time will \
                be reverseBaseTime + random value in reverseVarTime range. 
            reverseBaseTime (int): Base time for a random reverse in seconds. Must be a positive integer.
            reverseVarTime (int): Variable time for a random reverse in seconds. Must be a positive integer.
            mode (int): System mode; 0 = Manual, 1 = PC Control, and 2 = Internal Schedule.
            schedule (dict[str, tuple[int]]): Schedule for a week. The keys are the weekdays (Sunday-Saturday). \
                The values are a tuple of 24 bools that are either 1 for motor on or 0 for motor off
            checkForValidParams (bool, optional): Flag to raise Exceptions for invalid parameters when True. \
                Defaults to True.
        """
        self.systemID:          int     =  int(systemID)
        self.motorDirection:    bool    =  int(motorDirection)
        self.motorSpeed:        int     =  int(motorSpeed)
        self.randomReverse:     bool    = bool(randomReverse)
        self.mode:              int     =  int(mode)
        match reverseBaseTime : 
            case None   : self.reverseBaseTime = None
            case _      : self.reverseBaseTime = int(reverseBaseTime)
        match reverseVarTime : 
            case None   : self.reverseVarTime = None
            case _      : self.reverseVarTime = int(reverseVarTime)
        if(schedule != None) : 
            self.schedule: dict[str, tuple[bool]] = {}
            for key,val in schedule.items() : 
                self.schedule[str(key)] = self._FixTypeInTuple(val, bool)
        else: 
            self.schedule = None
        super().__init__(port, checkForValidParams)


    @staticmethod
    def BuildEmptySchedule() -> dict[str, tuple[bool]]:
        """Creates a schedule where the motor is off for all hours of every day.  

        Returns:
            dict[str, tuple[bool]]: Dictionary of the empty schedule. The keys are \
                the days of the week. The values are tuples of 24 zeros. 
        """
        schedule = {}
        for day in Params8229.week : 
            schedule[day] = tuple([0]*Params8229.hoursPerDay)
        return(schedule)


    def GetInit(self) -> str : 
        """Builds a string that represents the Params_8229 constructor with the \
        arguments set to the values of this class instance. 

        Returns:
            str: String that represents the Params_Interface constructor.
        """
        return('Morelia.Parameters.Params8229(port=\''+self.port+'\', systemID='+str(self.systemID)+
               ', motorDirection='+str(self.motorDirection)+', motorSpeed='+
               str(self.motorSpeed)+', randomReverse='+str(self.randomReverse)+
               ', reverseBaseTime='+str(self.reverseBaseTime)+', reverseVarTime='+
               str(self.reverseVarTime)+', mode='+str(self.mode)+', schedule='+
               str(self.schedule)+')')


    def _CheckParams(self) -> None :
        """Throws an exception if Params_8229 instance variable is an invalid value.

        Raises:
            Exception: The system ID must be a positive integer.
            Exception: The motor speed must be between 0-100%.
            Exception: The reverse base time (sec) must be a positive integer.
            Exception: The reverse variable time (sec) must be a positive integer.
            Exception: The mode must be 0, 1, or 2.
            Exception: The schedule must have exactly ('Sunday','Monday','Tuesday',\
                'Wednesday','Thursday','Friday','Saturday') as keys.
            Exception: There must be 24 items in the schedule for each day.
        """
        super()._CheckParams() 

        if(self.systemID < 0 or self.systemID > 999) : 
            raise Exception('The system ID must be between 0-999.')
        
        if(self.motorSpeed < 0 or self.motorSpeed > 100) :
            raise Exception('The motor speed must be between 0-100%.')
        
        if(self.reverseBaseTime != None) : 
            if(self.reverseBaseTime < 0 ) :
                raise Exception('The reverse base time (sec) must be a positive integer.')

        if(self.reverseVarTime != None) : 
            if(self.reverseVarTime < 0 ) :
                raise Exception('The reverse variable time (sec) must be a positive integer.')
        
        if(self.mode not in (0,1,2)) : 
            raise Exception('The mode must be 0, 1, or 2.')
        
        if(self.schedule != None) : 
            if(list(self.schedule.keys()).sort() != list(copy.copy(Params8229.week)).sort() ) : 
                raise Exception('The schedule must have exactly '+str(Params8229.week)+' as keys.')
            for day in self.schedule.values() : 
                if(len(day) != Params8229.hoursPerDay ) : 
                    raise Exception('There must be '+str(Params8229.hoursPerDay)+' items in the schedule for each day.')
            

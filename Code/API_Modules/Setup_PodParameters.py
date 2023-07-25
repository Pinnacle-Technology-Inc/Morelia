"""This module has several container classes for storing parameters for different POD devices.
"""

# enviornment imports
import copy

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Params_Interface :
    """Interface for a container class that stores parameters for a POD device.

    Attributes:
        port (str): Name of the COM port.
    """
    # NOTE Address all NOTE's when making a child of Params_Interface.


    def __init__(self, 
                 port: str,
                 checkForValidParams: bool = True 
                ) -> None :
        """Sets the instance variables of each POD parameter. Checks if the arguments are valid \
        when checkForValidParams is True.  

        Args:
            port (str): Name of the COM port.
            checkForValidParams (bool, optional): Flag to raise Exceptions for invalid \
                parameters when True. Defaults to True.
        """
        self.port: str = str(port)
        if(checkForValidParams) : 
            self._CheckParams()
        # NOTE Call super().__init__(port,checkForValidParams) in child class' __init__()
        #      AFTER assigning class instance variables.



    def GetInit(self) -> str : 
        """Builds a string that represents the Params_Interface constructor with the \
        arguments set to the values of this class instance. 

        Returns:
            str: String that represents the Params_Interface constructor.
        """
        return('Params_Interface(port=\''+self.port+'\')')
        # NOTE Overwrite this in child class.


    def _CheckParams(self) -> None : 
        """Throws an exception if Params_Interface instance variable is an invalid value.

        Raises:
            Exception: The port name must begin with COM.
        """
        if(not self.port.startswith('COM')) : 
            raise Exception('The port name must begin with COM.')
        # NOTE Call super()._CheckParams() at the TOP of the _CheckParams() in the 
        #      child class.


    @staticmethod
    def _FixTypeInTuple(arr: tuple, itemType: 'type') -> tuple['type']: 
        """Retypes each item of the arr arguemnt to itemType. 

        Args:
            arr (tuple): Tuple of items to be re-typed.
            itemType (type): Type to be casted to each tuple item.

        Returns:
            tuple[type]: Tuple with values of all itemType types.
        """
        n = len(arr)
        items = [None] * n
        for i in range(n) : 
            if(arr[i] != None) : 
                items[i] = itemType( arr[i] )
        return(tuple(items))
    

# ##########################################################################################


class Params_8206HR(Params_Interface) :
    """Container class that stores parameters for an 8206-HR POD device.

    Attributes:
        port (str): Name of the COM port.
        sampleRate (int): Sample rate in 100-2000 Hz range.
        preamplifierGain (int): Preamplifier gain. Should be 10x or 100x.
        lowPass (tuple[int]): Low-pass for EEG/EMG in 11-500 Hz range. 
    """

    lowPassLabels: tuple[str]  = ('EEG1', 'EEG2', 'EEG/EMG')
    """Tuple describing the items in the lowPass."""

    def __init__(self, 
                 port:              str,       
                 sampleRate:        int,       
                 preamplifierGain:  int,       
                 lowPass:           tuple[int],
                 checkForValidParams: bool = True
                ) -> None:
        """Sets the instance variables of each 8206-HR parameter. Checks if the arguments are \
        valid when checkForValidParams is True.  

        Args:
            port (str): Name of the COM port.
            sampleRate (int): Sample rate in 100-2000 Hz range.
            preamplifierGain (int): Preamplifier gain. Should be 10x or 100x.
            lowPass (tuple[int]): Low-pass for EEG/EMG in 11-500 Hz range. 
            checkForValidParams (bool, optional): Flag to raise Exceptions for invalid \
                parameters when True. Defaults to True.
        """
        self.sampleRate:        int         = int( sampleRate       ) 
        self.preamplifierGain:  int         = int( preamplifierGain ) 
        self.lowPass:           tuple[int]  = self._FixTypeInTuple( tuple(lowPass), int ) 
        super().__init__(port,checkForValidParams)


    def EEG1(self) -> int :
        """Gets the filter value of EEG1 in Hz from the low-pass. 

        Returns:
            int: EEG1 low-pass filter in Hz.
        """
        return(int(self.lowPass[0]))


    def EEG2(self) -> int :
        """Gets the filter value of EEG2 in Hz from the low-pass. 

        Returns:
            int: EEG2 low-pass filter in Hz.
        """
        return(int(self.lowPass[1]))
    

    def EEG3_EMG(self) -> int :
        """Gets the filter value of EEG3/EMG in Hz from the low-pass. 

        Returns:
            int: EEG3/EMG low-pass filter in Hz.
        """
        return(int(self.lowPass[2]))


    def GetInit(self) -> str : 
        """Builds a string that represents the Params_8206HR constructor with the \
        arguments set to the values of this class instance. 

        Returns:
            str: String that represents the Params_8206HR constructor.
        """
        return('Params_8206HR(port=\''+self.port+'\', sampleRate='+str(self.sampleRate)+
               ', preamplifierGain='+str(self.preamplifierGain)+', lowPass='+str(self.lowPass)+')')


    def _CheckParams(self) -> None :
        """Throws an exception if Params_8206HR instance variable is an invalid value.

        Raises:
            Exception: Sample rate must be between 100-2000 Hz.
            Exception: Preamplidier gain must be 10x or 100x.
            Exception: Low-pass EEG/EMG must be between 11-500 Hz.
        """
        super()._CheckParams() 

        if(self.sampleRate < 100 or self.sampleRate > 2000 ) : 
            raise Exception('Sample rate must be between 100-2000 Hz.')
        
        if(self.preamplifierGain != 10 and self.preamplifierGain != 100 ) : 
            raise Exception('Preamplidier gain must be 10x or 100x.')
        
        for eeg in self.lowPass : 
            if(eeg < 11 or eeg > 500) :
                raise Exception('Low-pass EEG/EMG must be between 11-500 Hz.')


# ##########################################################################################


class Params_8401HR(Params_Interface) :
    """Container class that stores parameters for an 8401-HR POD device.

    Attributes:
        port (str): Name of the COM port.
        preampDevice (str): Name of the mouse/rat preamplifier device.
        sampleRate (int): Sample rate (2000-20000 Hz).
        muxMode (bool): Using mux mode when True, false otherwise.
        preampGain (tuple[int]): Preamplifier gain (1, 10, or 100) for all channels.
        ssGain (tuple[int]): Second stage gain (1 or 5) for all channels.
        highPass (tuple[float]): High-pass filter (0, 0.5, 1, or 10 Hz) for all channels.
        lowPass (tuple[int]): Low-pass filter (21-15000 Hz) for all channels.
        bias (tuple[float]): Bias voltage (+/- 2.048 V) for all channels.
        dcMode (tuple[str]): DC mode (VBIAS or AGND) for all channels.
    """

    channelLabels: tuple[str] = ('A','B','C','D')
    """Tuple listing the four channel characters in order."""

    def __init__(self, 
                 port:          str,            
                 preampDevice:  str,            
                 sampleRate:    int,            
                 muxMode:       bool,           
                 preampGain:    tuple[int  ],   
                 ssGain:        tuple[int  ],   
                 highPass:      tuple[float],   
                 lowPass:       tuple[int  ],   
                 bias:          tuple[float],   
                 dcMode:        tuple[str  ],   
                 checkForValidParams: bool = True
                ) -> None:
        """Sets the instance variables of each 8401-HR parameter. Checks if the arguments are \
        valid when checkForValidParams is True.  

        Args:
            port (str): Name of the COM port.
            preampDevice (str): Name of the mouse/rat preamplifier device.
            sampleRate (int): Sample rate (2000-20000 Hz).
            muxMode (bool): Using mux mode when True, false otherwise.
            preampGain (tuple[int]): Preamplifier gain (1, 10, or 100) for all channels.
            ssGain (tuple[int]): Second stage gain (1 or 5) for all channels.
            highPass (tuple[float]): High-pass filter (0, 0.5, 1, or 10 Hz) for all channels.
            lowPass (tuple[int]): Low-pass filter (21-15000 Hz) for all channels.
            bias (tuple[float]): Bias voltage (+/- 2.048 V) for all channels.
            dcMode (tuple[str]): DC mode (VBIAS or AGND) for all channels.
            checkForValidParams (bool, optional): Flag to raise Exceptions for invalid \
                parameters when True. Defaults to True.
        """
        self.preampDevice:      str             =  str( preampDevice )
        self.sampleRate:        int             =  int( sampleRate   )
        self.muxMode:           bool            = bool( muxMode      )
        self.preampGain:        tuple[int  ]    = self._FixTypeInTuple( tuple( preampGain ), int   )
        self.ssGain:            tuple[int  ]    = self._FixTypeInTuple( tuple( ssGain     ), int   )
        self.highPass:          tuple[float]    = self._FixTypeInTuple( tuple( highPass   ), float )
        self.lowPass:           tuple[int  ]    = self._FixTypeInTuple( tuple( lowPass    ), int   )
        self.bias:              tuple[float]    = self._FixTypeInTuple( tuple( bias       ), float )
        self.dcMode:            tuple[str  ]    = self._FixTypeInTuple( tuple( dcMode     ), str   )
        super().__init__(port,checkForValidParams)


    def GetInit(self) -> str : 
        """Builds a string that represents the Params_8401HR constructor with the \
        arguments set to the values of this class instance. 

        Returns:
            str: String that represents the Params_8401HR constructor.
        """
        return('Params_8401HR(port=\''+self.port+'\', preampDevice=\''+str(self.preampDevice)+
               '\', sampleRate='+str(self.sampleRate)+', muxMode='+str(self.muxMode)+
               ', preampGain='+str(self.preampGain)+', ssGain='+str(self.ssGain)+
               ', highPass='+str(self.highPass)+', lowPass='+str(self.lowPass)+
               ', bias='+str(self.bias)+', dcMode='+str(self.dcMode)+')')
    

    def _CheckParams(self) -> None :
        """Throws an exception if Params_8401HR instance variable is an invalid value.

        Raises:
            Exception: Mouse/rat preamplifier does not exist.
            Exception: Sample rate must be between 2000-20000 Hz.
            Exception: EEG/EMG preamplifier gain must be 10x or 100x. For biosensors, the preampGain is None.
            Exception: The second stage gain must be 1x or 5x; set gain to None if no-connect.
            Exception: The high-pass filter must be 0.5, 1, or 10 Hz. If the channel is DC, input 0.
            Exception: The low-pass filter must be between 21-15000 Hz.
            Exception: The bias voltage must be +/- 2.048 V.
            Exception: The DC mode must be VBIAS or AGND.
        """
        super()._CheckParams() 

        from PodDevice_8401HR import POD_8401HR
        devices = POD_8401HR.GetSupportedPreampDevices()
        if(self.preampDevice not in devices) :
            raise Exception('Mouse/rat preamplifier must be in '+str(devices)+'.')
        
        if(self.sampleRate < 2000 or self.sampleRate > 20000) : 
            raise Exception('Sample rate must be between 2000-20000 Hz.')
        
        for pg in self.preampGain : 
            if(pg != 10 and pg != 100 and pg != None): 
                raise Exception('EEG/EMG preamplifier gain must be 10x or 100x. For biosensors, the preampGain is None.')
        
        for ss in self.ssGain :
            if(ss != 1 and ss != 5 and ss != None): 
                raise Exception('The second stage gain must be 1x or 5x; set gain to None if no-connect.')
            
        for hp in self.highPass : 
            if(hp != None) : 
                if(hp not in [0., 0.5, 1., 10.]) : 
                    raise Exception('The high-pass filter must be 0.5, 1, or 10 Hz. If the channel is DC, input 0.')
            
        for lp in self.lowPass : 
            if(lp != None) : 
                if(lp < 21 or lp > 15000) : 
                    raise Exception('The low-pass filter must be between 21-15000 Hz.')
            
        for bs in self.bias :
            if(bs != None):
                if(bs < -2.048 or bs > 2.048) : 
                    raise Exception('The bias voltage must be +/- 2.048 V.')
            
        for dc in self.dcMode : 
            if(dc != None) : 
                if(dc not in ['VBIAS','AGND']) :                     raise Exception('The DC mode must be VBIAS or AGND.')

            

# ##########################################################################################


class Params_8229(Params_Interface) :
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
        for day in Params_8229.week : 
            schedule[day] = tuple([0]*Params_8229.hoursPerDay)
        return(schedule)


    def GetInit(self) -> str : 
        """Builds a string that represents the Params_8229 constructor with the \
        arguments set to the values of this class instance. 

        Returns:
            str: String that represents the Params_Interface constructor.
        """
        return('Params_8229(port=\''+self.port+'\', systemID='+str(self.systemID)+
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
            if(list(self.schedule.keys()).sort() != list(copy.copy(Params_8229.week)).sort() ) : 
                raise Exception('The schedule must have exactly '+str(Params_8229.week)+' as keys.')
            for day in self.schedule.values() : 
                if(len(day) != Params_8229.hoursPerDay ) : 
                    raise Exception('There must be '+str(Params_8229.hoursPerDay)+' items in the schedule for each day.')
            

# ##########################################################################################


class Params_8480SC(Params_Interface) :
    """Container class that stores parameters for an 8401-HR POD device.

    Attributes:
        port (str): Name of the COM port.
        stimulus (tuple[int]): Stimulus configuration on selected channel.
        preamp (int): Preamp value (0-1023).
        ledCurrent (tuple[int]): Led-Current (0-600 mA) for both channels. 
        ttlPUllups (int): TTL Pullups disabled for value 0, pullups enabled for values that are non-zero.
        estimCurrent (tuple[int]): Estim-Current (0-100 %) for both channels.
        syncConfig (int): Sets Sync-Config byte.
        ttlSetup (tuple[int]): TTL-Setup for selected channel.
    """

    def __init__(self,
        port:  str,
        stimulus = tuple[int],
        preamp = int,
        ledCurrent = tuple[int],
        ttlPullups = int,
        estimCurrent = tuple[int],
        syncConfig = int,
        ttlSetup = tuple[int],                                                    
        checkForValidParams: bool = True
        ) -> None:
        """Sets the member variables of each 8480-SC parameter. Checks if the arguments are \
        valid when checkForValidParams is True.  

        Args:
            port (str): Name of the COM port.
            stimulus (tuple[int]): Stimulus configuration on selected channel.
            preamp (int): Preamp value (0-1023).
            ledCurrent (tuple[int]): Led-Current (0-600 mA) for both channels. 
            ttlPUllups (int): pullups disabled for value 0, pullups enabled for values that are non-zero.
            estimCurrent (tuple[int]): Estim-Current (0-100 %) for both channels.
            syncConfig (int): Sets Sync-Config byte.
            ttlSetup (tuple[int]): TTL-Setup for selected channel.
            checkForValidParams (bool, optional): Flag to raise Exceptions for invalid \
                parameters when True. Defaults to True.
        """
        self.stimulus:       tuple[int]  =  self._FixTypeInTuple( tuple(stimulus), int )
        self.preamp:         int         =  int( preamp)
        self.ledCurrent:     tuple[int]  =  self._FixTypeInTuple( tuple(ledCurrent), int )
        self.ttlPullups:     int         =  int( ttlPullups)
        self.estimCurrent:   tuple[int]  =  self._FixTypeInTuple( tuple(estimCurrent), int )
        self.syncConfig:     int         =  int( syncConfig)
        self.ttlSetup:       tuple[int]  =  self._FixTypeInTuple( tuple(ttlSetup), int )
        super().__init__(port,checkForValidParams)


    def GetInit(self) -> str : 
        """Builds a string that represents the Params_8480SC constructor with the \
        arguments set to the values of this class instance. 

        Returns:
            str: String that represents the Params_8480SC constructor.
        """
        return('Params_8401HR(port=\''+self.port+'\', preamp=\''+str(self.preamp)+
               '\', ledCurrent='+str(self.ledCurrent)+', ttlPullups='+str(self.ttlPullups)+
               ', estimCurrent='+str(self.estimCurrent)+', syncConfig='+str(self.syncConfig)+
               ', ttlSetup='+str(self.ttlSetup)+')')


    def ledCurrent_CH0(self) -> int :
        """Gets the ledCurrent value for Channel 0. 

        Returns:
            int: Channel 0 ledCurrent in mA.
        """
        return(int(self.ledCurrent[0]))
    

    def ledCurrent_CH1(self) -> int :
        """Gets the ledCurrent value for Channel 1. 

        Returns:
            int: Channel 1 ledCurrent in mA.
        """
        return(int(self.ledCurrent[1]))
    

    def estimCurrent_CH0(self) -> int :
        """Gets the estimCurrent value for Channel 0.

        Returns:
            int: Channel 0 estimCurrent in percentage.
        """
        return(int(self.estimCurrent[0]))
    

    def estimCurrent_CH1(self) -> int :
        """Gets the estimCurrent value for Channel 1. 

        Returns:
            int: Channel 1 estimCurrent in percentage.
        """
        return(int(self.estimCurrent[1]))
    
  
    def _CheckParams(self) -> None :
        """Throws an exception if Params_8206HR member variable is an invalid value.

        Raises:
            Exception: The preamp must be between 0-1023.
            Exception: Led-Curent must be between 0-600.
            Exception: Estim-Current must be between 0-100.
        """
        super()._CheckParams() 

        if(self.preamp < 0 and self.preamp > 1023 ) : 
            raise Exception('The preamp must be between 0-1023.')

        for channel in self.ledCurrent : 
            if(channel < 0 or channel > 600) :
                raise Exception('Led-Curent must be between 0-600.')
            
        for channel in self.estimCurrent : 
            if(channel < 0 or channel > 100) :
                raise Exception('Estim-Current must be between 0-100.')

    
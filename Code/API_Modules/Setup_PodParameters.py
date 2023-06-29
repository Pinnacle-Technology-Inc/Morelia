"""This module has several container classes for storing parameters for different POD devices.
"""

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Params_Interface :
    """Interface for a container class that stores parameters for a POD device.
    """
    # NOTE Address all NOTE's when making a child of Params_Interface.

    
    def __init__(self, 
                 port: str,
                 checkForValidParams: bool = True 
                ) -> None :
        """Sets the member variables of each POD parameter. Checks if the arguments are valid \
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
        """Throws an exception if Params_Interface member variable is an invalid value.

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
        return(tuple([itemType(x) for x in arr]))
    

# ##########################################################################################


class Params_8206HR(Params_Interface) :

    def __init__(self, 
                 port:              str,       
                 sampleRate:        int,       
                 preamplifierGain:  int,       
                 lowPass:           tuple[int],
                 checkForValidParams: bool = True
                ) -> None:
        """Sets the member variables of each 8206-HR parameter. Checks if the arguments are \
        valid when checkForValidParams is True.  

        Args:
            port (str): Name of the COM port 
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
        """Throws an exception if Params_8206HR member variable is an invalid value.

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
        """Sets the member variables of each 8401-HR parameter. Checks if the arguments are \
        valid when checkForValidParams is True.  

        Args:
            port (str): Name of the COM port .
            preampDevice (str): Name of the mouse/rat preamplifier device.
            sampleRate (int): Sample rate (2000-20000 Hz).
            muxMode (bool): Using mux mode when True, false otherwise.
            preampGain (tuple[int  ]): Preamplifier gain (1, 10, or 100) for all channels.
            ssGain (tuple[int  ]): Second stage gain (1 or 5) for all channels.
            highPass (tuple[float]): High-pass filter (0, 0.5, 1, or 10 Hz) for all channels.
            lowPass (tuple[int  ]): Low-pass filter (21-15000 Hz) for all channels.
            bias (tuple[float]): Bias voltage (+/- 2.048 V) for all channels .
            dcMode (tuple[str  ]): DC mode (VBIAS or AGND) for all channels.
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
        return('Params_8401HR(port=\''+self.port+'\', preampDevice='+str(self.preampDevice)+
               ', sampleRate='+str(self.sampleRate)+', muxMode='+str(self.muxMode)+
               ', preampGain='+str(self.preampGain)+', ssGain='+str(self.ssGain)+
               ', highPass='+str(self.highPass)+', lowPass='+str(self.lowPass)+
               ', bias='+str(self.bias)+', dcMode='+str(self.dcMode)+')')
    

    def _CheckParams(self) -> None :
        """Throws an exception if Params_8401HR member variable is an invalid value.

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
            if(hp not in [0., 0.5, 1., 10.]) : 
                raise Exception('The high-pass filter must be 0.5, 1, or 10 Hz. If the channel is DC, input 0.')
            
        for lp in self.lowPass : 
            if(lp < 21 or lp > 15000) : 
                raise Exception('The low-pass filter must be between 21-15000 Hz.')
            
        for bs in self.bias :
            if(bs < -2.048 or bs > 2.048) : 
                raise Exception('The bias voltage must be +/- 2.048 V.')
            
        for dc in self.dcMode : 
            if(dc not in ['VBIAS','AGND']) : 
                raise Exception('The DC mode must be VBIAS or AGND.')
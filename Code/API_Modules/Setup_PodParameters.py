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

    def __init__(self, 
                 port: str,  # name of the COM port 
                 checkForValidParams: bool = True # flag to raise Exceptions for invalid parameters when True
                ) -> None :
        self.port: str = str(port)
        if(checkForValidParams) : 
            self._CheckParams()

    def GetInit(self) -> str : 
        return('Params_Interface(port=\''+self.port+'\')')

    def _CheckParams(self) -> None : 
        if(not self.port.startswith('COM')) : 
            raise Exception('The port name must begin with COM.')

    @staticmethod
    def _FixTypeInTuple(arr: tuple, itemType: 'type') -> tuple['type']: 
        return(tuple([itemType(x) for x in arr]))
    

# ##########################################################################################


class Params_8206HR(Params_Interface) :

    def __init__(self, 
                 port:              str,        # name of the COM port 
                 sampleRate:        int,        # sample rate in 100-2000 Hz range.
                 preamplifierGain:  int,        # preamplifier gain. Should be 10x or 100x.
                 lowPass:           tuple[int], # low-pass for EEG/EMG in 11-500 Hz range. 
                 checkForValidParams: bool = True
                ) -> None:
        self.sampleRate:        int         = int( sampleRate       ) 
        self.preamplifierGain:  int         = int( preamplifierGain ) 
        self.lowPass:           tuple[int]  = self._FixTypeInTuple( tuple(lowPass), int ) 
        super().__init__(port,checkForValidParams)

    def EEG1(self) -> int :
        return(int(self.lowPass[0]))

    def EEG2(self) -> int :
        return(int(self.lowPass[1]))

    def EEG3_EMG(self) -> int :
        return(int(self.lowPass[2]))

    def GetInit(self) -> str : 
        return('Params_8206HR(port=\''+self.port+'\', sampleRate='+str(self.sampleRate)+
               ', preamplifierGain='+str(self.preamplifierGain)+', lowPass='+str(self.lowPass)+')')

    def _CheckParams(self) -> None :
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
                 port:          str,            # name of the COM port 
                 preampDevice:  str,            # name of the mouse/rat preamplifier device
                 sampleRate:    int,            # sample rate (2000-20000 Hz)
                 muxMode:       bool,           # using mux mode when True, false otherwise
                 preampGain:    tuple[int  ],   # preamplifier gain (1, 10, or 100) for all channels
                 ssGain:        tuple[int  ],   # second stage gain (1 or 5) for all channels
                 highPass:      tuple[float],   # high-pass filter (0, 0.5, 1, or 10 Hz) for all channels
                 lowPass:       tuple[int  ],   # low-pass filter (21-15000 Hz) for all channels
                 bias:          tuple[float],   # bias voltage (+/- 2.048 V) for all channels 
                 dcMode:        tuple[str  ],   # DC mode (VBIAS or AGND) for all channels
                 checkForValidParams: bool = True
                ) -> None:
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
        return('Params_8401HR(port=\''+self.port+'\', preampDevice='+str(self.preampDevice)+
               ', sampleRate='+str(self.sampleRate)+', muxMode='+str(self.muxMode)+
               ', preampGain='+str(self.preampGain)+', ssGain='+str(self.ssGain)+
               ', highPass='+str(self.highPass)+', lowPass='+str(self.lowPass)+
               ', bias='+str(self.bias)+', dcMode='+str(self.dcMode)+')')
    
    def _CheckParams(self) -> None :
        super()._CheckParams() 

        from PodDevice_8401HR import POD_8401HR
        devices = POD_8401HR.GetSupportedPreampDevices()
        if(self.preampDevice not in devices) :
            raise Exception('Mouse/rat preamplifier must be in '+str(devices)+'.')
        
        if(self.sampleRate < 2000 or self.sampleRate > 20000) : 
            raise Exception('Sample rate must be between 2000-20000 Hz.')
        
        for pg in self.preampGain : 
            if(pg != 10 and pg != 100 and pg != None): 
                raise Exception('[!] EEG/EMG preampGain must be 10 or 100. For biosensors, the preampGain is None.')
        
        for ss in self.ssGain :
            if(ss != 1 and ss != 5 and ss != None): 
                raise Exception('[!] The ssGain must be 1 or 5; set ssGain to None if no-connect.')
            
        for hp in self.highPass : 
            if(hp not in [0., 0.5, 1., 10.]) : 
                raise Exception('The high-pass filter must be 0.5, 1, or 10 Hz. If the channel is DC, input 0.')
            
        for lp in self.lowPass : 
            if(lp < 21 or lp > 15000) : 
                raise Exception('The low-pass filter must be between 21-15000 Hz.')
            
        for bs in self.bias :
            if(bs < -2.048 or bs > 2.048) : 
                raise Exception('The bias voltage must be +/- 2.048 V. ')
            
        for dc in self.dcMode : 
            if(dc not in ['VBIAS','AGND']) : 
                raise Exception('The DC mode must be VBIAS or AGND.')
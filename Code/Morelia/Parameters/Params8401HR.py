# local imports 
from Morelia.Parameters import Params
from Morelia.Devices    import Pod8401HR

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"


class Params8401HR(Params) :
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
        return('Morelia.Parameters.Params8401HR(port=\''+self.port+'\', preampDevice=\''+str(self.preampDevice)+
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

        devices = Pod8401HR.GetSupportedPreampDevices()
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
                if(dc not in ['VBIAS','AGND']) :                     
                    raise Exception('The DC mode must be VBIAS or AGND.')

            
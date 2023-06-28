# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"


class Params_Interface : 

    def __init__(self, port: str) -> None :
        self.port: str = port # name of the COM port 

    def GetInit(self) -> str : 
        return('Params_Interface(port=\''+self.port+'\')')


# ##########################################################################################

class Params_8206HR(Params_Interface) :

    def __init__(self, 
                 port: str, sampleRate: int, 
                 preamplifierGain: int, 
                 lowPass: tuple[int]
                ) -> None:
        super().__init__(port)
        self.sampleRate:        int         =   int( sampleRate       ) # sample rate in 100-2000 Hz range.
        self.preamplifierGain:  int         =   int( preamplifierGain ) # preamplifier gain. Should be 10x or 100x.
        self.lowPass:           tuple[int]  = tuple( lowPass          ) # low-pass for EEG/EMG in 11-500 Hz range. 

    def GetInit(self) -> str : 
        return('Params_8206HR(port=\''+self.port+'\', sampleRate='+str(self.sampleRate)+
               ', preamplifierGain='+str(self.preamplifierGain)+', lowPass='+str(self.lowPass)+')')

    def EEG1(self) -> int :
        return(int(self.lowPass[0]))

    def EEG2(self) -> int :
        return(int(self.lowPass[1]))

    def EEG3_EMG(self) -> int :
        return(int(self.lowPass[2]))
    

# ##########################################################################################


class Params_8401HR(Params_Interface) :
    
    channels: list[str] = ['A','B','C','D']

    A: int = 0
    B: int = 1
    C: int = 2
    D: int = 3

    def __init__(self, 
                 port: str, 
                 preampDevice: str, 
                 sampleRate: int, 
                 muxMode: bool, 
                 preampGain: tuple[int], 
                 ssGain: tuple[int], 
                 highPass: tuple[float], 
                 lowPass: tuple[int], 
                 bias: tuple[float], 
                 dcMode: tuple[str] 
                ) -> None:
        super().__init__(port)
        self.preampDevice:      str             =   str(preampDevice ) # name of the mouse/rat preamplifier device
        self.sampleRate:        int             =   int(sampleRate   ) # sample rate (2000-20000 Hz)
        self.muxMode:           bool            =  bool(muxMode      ) # using mux mode when True, false otherwise
        self.preampGain:        tuple[int]      = tuple(preampGain   ) # preamplifier gain (1, 10, or 100) for all channels
        self.ssGain:            tuple[int]      = tuple(ssGain       ) # second stage gain (1 or 5) for all channels
        self.highPass:          tuple[float]    = tuple(highPass     ) # high-pass filter (0, 0.5, 1, or 10 Hz) for all channels
        self.lowPass:           tuple[int]      = tuple(lowPass      ) # low-pass filter (21-15000 Hz) for all channels
        self.bias:              tuple[float]    = tuple(bias         ) # bias voltage (+/- 2.048 V) for all channels 
        self.dcMode:            tuple[str]      = tuple(dcMode       ) # DC mode (VBIAS or AGND) for all channels

    def GetInit(self) -> str : 
        return('Params_8401HR(port=\''+self.port+'\', preampDevice='+str(self.preampDevice)+
               ', sampleRate='+str(self.sampleRate)+', muxMode='+str(self.muxMode)+
               ', preampGain='+str(self.preampGain)+', ssGain='+str(self.ssGain)+
               ', highPass='+str(self.highPass)+', lowPass='+str(self.lowPass)+
               ', bias='+str(self.bias)+', dcMode='+str(self.dcMode)+')')
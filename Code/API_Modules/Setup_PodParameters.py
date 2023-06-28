
# local imports 
from PodDevice_8401HR import POD_8401HR

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"


class Params_Interface : 

    keys: list = ['Port']

    def __init__(self,  paramDict: dict = None) -> None :
        if(paramDict != None) : 
            self.IsParamDictValid(paramDict)
            self._SetParamsFromDict(paramDict)
        else :
            self._SetDefaults()

    def _SetDefaults(self) : 
        self.port: str = '' # name of the COM port 

    def _SetParamsFromDict(self, paramDict: dict) -> None : 
        pass
    
    def IsParamDictValid(self, paramDict: dict, name: str = 'this device') -> bool : 
        pass

    def GetDictOfParams(self) -> dict :
        pass



# ##########################################################################################

class Params_8206HR(Params_Interface) :

    keys:           list[str] = Params_Interface.keys + ['Sample Rate','Preamplifier Gain','Low-pass']
    keys_lowPass:   list[str] = ['EEG1','EEG2','EEG3/EMG']
       
    def _SetDefaults(self) : 
        self.port:              str         = ''        # name of the COM port 
        self.sampleRate:        int         = 0         # sample rate in 100-2000 Hz range.
        self.preamplifierGain:  int         = 0         # preamplifier gain. Should be 10x or 100x.
        self.lowPass:           tuple[int]  = (0,0,0)   # low-pass for EEG/EMG in 11-500 Hz range. 

    def _SetParamsFromDict(self, paramDict: dict[str,str|int|dict[str,int]]) -> None : 
        self.port:              str         =   str( paramDict[self.keys[0]] )
        self.sampleRate:        int         =   int( paramDict[self.keys[1]] )
        self.preamplifierGain:  int         =   int( paramDict[self.keys[2]] )
        self.lowPass:           tuple[int]  = tuple( paramDict[self.keys[3]].values() )

    def EEG1(self) -> int :
        return(self.lowPass[0])

    def EEG2(self) -> int :
        return(self.lowPass[1])

    def EEG3_EMG(self) -> int :
        return(self.lowPass[2])
    
    def IsParamDictValid(self,  paramDict: dict[str,str|int|dict[str,int]], name: str = 'this device') -> bool : 
        # check that all params exist 
        if(list(paramDict.keys()) != self.keys ) :
            raise Exception('[!] Invalid parameters for '+str(name)+'.')
        # check type of each specific command 
        if( not(    isinstance( paramDict[self.keys[0]], str  )     # keys[0] = 'Port'
                and isinstance( paramDict[self.keys[1]], int  )     # keys[1] = 'Sample Rate'
                and isinstance( paramDict[self.keys[2]], int  )     # keys[2] = 'Preamplifier Gain'
                and isinstance( paramDict[self.keys[3]], dict ) )   # keys[3] = 'Low-pass'
        ) : 
            raise Exception('[!] Invalid parameter value types for '+str(name)+'.')
        # check that low-pass is correct
        if( list(paramDict[self.keys[3]].keys()) != self.keys_lowPass ) : # self.keys[3] = 'Low-pass' 
            raise Exception('[!] Invalid low-pass parameters for '+str(name)+'.')
        # check type of low-pass
        for lowPassVal in paramDict[self.keys[3]].values() : # self.keys[3] = 'Low-pass' 
            if( not isinstance(lowPassVal, int) ) : 
                raise Exception('[!] Invalid low-pass value types for '+str(name)+'.')
        # no exception raised 
        return(True)
    
    def GetDictOfParams(self) -> dict :
        return({
            self.keys[0] : self.port,
            self.keys[1] : self.sampleRate,
            self.keys[2] : self.preamplifierGain,
            self.keys[3] : { self.keys_lowPass[0] : self.lowPass[0],
                             self.keys_lowPass[1] : self.lowPass[1],
                             self.keys_lowPass[2] : self.lowPass[2]}
        })


# ##########################################################################################


class Params_8401HR(Params_Interface) :
    
    keys:           list[str] = Params_Interface.keys + ['Preamplifier Device','Sample Rate','Mux Mode','Preamplifier Gain','Second Stage Gain','High-pass','Low-pass','Bias','DC Mode']
    keys_channel:   list[str] = ['A','B','C','D']

    A: int = 0
    B: int = 1
    C: int = 2
    D: int = 3

    def _SetDefaults(self) : 
        self.port:              str             = ''            # name of the COM port 
        self.preampDevice:      str             = ''            # name of the mouse/rat preamplifier device
        self.sampleRate:        int             = 0             # sample rate (2000-20000 Hz)
        self.muxMode:           bool            = False         # using mux mode when True, false otherwise
        self.preampGain:        tuple[int]      = (0,0,0,0)     # preamplifier gain (1, 10, or 100) for all channels
        self.ssGain:            tuple[int]      = (0,0,0,0)     # second stage gain (1 or 5) for all channels
        self.highPass:          tuple[float]    = (0.,0.,0.,0.) # high-pass filter (0, 0.5, 1, or 10 Hz) for all channels
        self.lowPass:           tuple[int]      = (0,0,0,0)     # low-pass filter (21-15000 Hz) for all channels
        self.bias:              tuple[float]    = (0.,0.,0.,0.) # bias voltage (+/- 2.048 V) for all channels 
        self.dcMode:            tuple[str]      = ('','','','') # DC mode (VBIAS or AGND) for all channels
    
    def _SetParamsFromDict(self, paramDict: dict[str,(str|int|dict)]) -> None : 
        self.port:              str             =   str( paramDict[self.keys[0]]            ) # keys[0] = 'Port'
        self.preampDevice:      str             =   str( paramDict[self.keys[1]]            ) # keys[1] = 'Preamplifier Device'
        self.sampleRate:        int             =   int( paramDict[self.keys[2]]            ) # keys[2] = 'Sample Rate'
        self.muxMode:           bool            =  bool( paramDict[self.keys[3]]            ) # keys[3] = 'Mux Mode'
        self.preampGain:        tuple[int]      = tuple( paramDict[self.keys[4]].values()   ) # keys[4] = 'Preamplifier Gain'
        self.ssGain:            tuple[int]      = tuple( paramDict[self.keys[5]].values()   ) # keys[5] = 'Second Stage Gain'
        self.highPass:          tuple[float]    = tuple( paramDict[self.keys[6]].values()   ) # keys[6] = 'High-pass'
        self.lowPass:           tuple[int]      = tuple( paramDict[self.keys[7]].values()   ) # keys[7] = 'Low-pass'
        self.bias:              tuple[float]    = tuple( paramDict[self.keys[8]].values()   ) # keys[8] = 'Bias'
        self.dcMode:            tuple[str]      = tuple( paramDict[self.keys[9]].values()   ) # keys[9] = 'DC Mode'


    def IsParamDictValid(self, paramDict: dict, name: str = 'this device') -> bool : 
        # check that all params exist 
        if(list(paramDict.keys()) != self.keys ) :
            raise Exception('[!] Invalid parameters for '+str(name)+'.')
        # check type of each specific command 
        if( not(
                    isinstance( paramDict[self.keys[0]],   str  ) # keys[0] = 'Port'
                and isinstance( paramDict[self.keys[1]],   str  ) # keys[1] = 'Preamplifier Device'
                and isinstance( paramDict[self.keys[2]],   int  ) # keys[2] = 'Sample Rate'
                and isinstance( paramDict[self.keys[3]],   bool ) # keys[3] = 'Mux Mode'
                and isinstance( paramDict[self.keys[4]],   dict ) # keys[4] = 'Preamplifier Gain'
                and isinstance( paramDict[self.keys[5]],   dict ) # keys[5] = 'Second Stage Gain'
                and isinstance( paramDict[self.keys[6]],   dict ) # keys[6] = 'High-pass'
                and isinstance( paramDict[self.keys[7]],   dict ) # keys[7] = 'Low-pass'
                and isinstance( paramDict[self.keys[8]],   dict ) # keys[8] = 'Bias'
                and isinstance( paramDict[self.keys[9]],   dict ) # keys[9] = 'DC Mode'
            )
        ) : 
            raise Exception('[!] Invalid parameter value types for '+str(name)+'.')
        # check preamp 
        if(not POD_8401HR.IsPreampDeviceSupported(paramDict['Preamplifier Device'])) :
            raise Exception('[!] Preamplifier '+str(paramDict['Preamplifier Device'])+' is not supported for '+str(name)+'.')
        # check ABCD channel value types
        self._IsChannelTypeValid( paramDict[self.keys[4]],    int,      name) # keys[4] = 'Preamplifier Gain'
        self._IsChannelTypeValid( paramDict[self.keys[5]],    int,      name) # keys[5] = 'Second Stage Gain'
        self._IsChannelTypeValid( paramDict[self.keys[6]],    float,    name) # keys[6] = 'High-pass'
        self._IsChannelTypeValid( paramDict[self.keys[7]],    int,      name) # keys[7] = 'Low-pass'
        self._IsChannelTypeValid( paramDict[self.keys[8]],    float,    name) # keys[8] = 'Bias'
        self._IsChannelTypeValid( paramDict[self.keys[9]],    str,      name) # keys[9] = 'DC Mode'
        # no exception raised 
        return(True)
    

    def _IsChannelTypeValid(self, chdict: dict, isType, name: str = 'this device') -> bool :
        """Checks that the keys and values for a given channel are valid.

        Args:
            chdict (dict): dictionary with ABCD keys and isType type values.
            isType (bool): data type.

        Raises:
            Exception: Channel dictionary is empty.
            Exception: Invalid channel keys.
            Exception: Invalid channel value.

        Returns:
            bool: True for valid parameters.
        """
        # is dict empty?
        if(len(chdict)==0) : 
            raise Exception('[!] Channel dictionary is empty for '+str(name)+'.')
        # check that keys are ABCD
        if(list(chdict.keys()) != self.keys_channel ) :
            raise Exception('[!] Invalid channel keys for '+str(name)+'.')
        for value in chdict.values() :
            if( (value != None) and (not isinstance(value, isType)) ) :
                raise Exception('[!] Invalid channel value type for '+str(name)+'.')
        return(True)
    
    def GetDictOfParams(self) -> dict :
        A = self.A
        B = self.B
        C = self.C
        D = self.D
        return({
            self.keys[0] : self.port,
            self.keys[1] : self.preampDevice,
            self.keys[2] : self.sampleRate,
            self.keys[3] : self.muxMode,
            self.keys[4] : {
                self.keys_channel[A] : self.preampGain[A],
                self.keys_channel[B] : self.preampGain[B],
                self.keys_channel[C] : self.preampGain[C],
                self.keys_channel[D] : self.preampGain[D],
            },
            self.keys[5] : {
                self.keys_channel[A] : self.ssGain[A],
                self.keys_channel[B] : self.ssGain[B],
                self.keys_channel[C] : self.ssGain[C],
                self.keys_channel[D] : self.ssGain[D],
            },
            self.keys[6] : {
                self.keys_channel[A] : self.highPass[A],
                self.keys_channel[B] : self.highPass[B],
                self.keys_channel[C] : self.highPass[C],
                self.keys_channel[D] : self.highPass[D],
            },
            self.keys[7] : {
                self.keys_channel[A] : self.lowPass[A],
                self.keys_channel[B] : self.lowPass[B],
                self.keys_channel[C] : self.lowPass[C],
                self.keys_channel[D] : self.lowPass[D],
            },
            self.keys[8] : {
                self.keys_channel[A] : self.bias[A],
                self.keys_channel[B] : self.bias[B],
                self.keys_channel[C] : self.bias[C],
                self.keys_channel[D] : self.bias[D],
            },
            self.keys[9] : {
                self.keys_channel[A] : self.dcMode[A],
                self.keys_channel[B] : self.dcMode[B],
                self.keys_channel[C] : self.dcMode[C],
                self.keys_channel[D] : self.dcMode[D],
            },
        })
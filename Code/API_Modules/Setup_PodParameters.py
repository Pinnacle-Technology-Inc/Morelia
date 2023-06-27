# enviornment imports
import copy

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
    
    def IsParamDictValid(self, paramDict: dict) -> bool : 
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
        if(list(paramDict.keys()).sort() != copy.copy(self.keys).sort() ) :
            raise Exception('[!] Invalid parameters for '+str(name)+'.')
        # check type of each specific command 
        if( not(    isinstance( paramDict[self.keys[0]], str  )     # 'Port'
                and isinstance( paramDict[self.keys[1]], int  )     # 'Sample Rate'
                and isinstance( paramDict[self.keys[2]], int  )     # 'Preamplifier Gain'
                and isinstance( paramDict[self.keys[3]], dict ) )   # 'Low-pass'
        ) : 
            raise Exception('[!] Invalid parameter value types for '+str(name)+'.')
        # check that low-pass is correct
        if( list(paramDict[self.keys[3]].keys()).sort() != copy.copy(self.keys_lowPass).sort() ) : # self.keys[3] = 'Low-pass' 
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
    pass
    




# ##########################################################################################


class Params_8229(Params_Interface) :
    pass



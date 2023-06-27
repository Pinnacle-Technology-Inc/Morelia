# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"


class Params_Interface : 

    def __init__(self, port: str = '') -> None :
        self.port: str = port # name of the COM port 



# ##########################################################################################

class Params_8206HR(Params_Interface) :

    def __init__(self, port: str = '', sampleRate: int = 0, preamplifierGain: int = 0, lowPass: tuple[int] = (0,0,0)) -> None:
        super().__init__(port)
        self.sampleRate:        int         = sampleRate        # sample rate in 100-2000 Hz range.
        self.preamplifierGain:  int         = preamplifierGain  # preamplifier gain. Should be 10x or 100x.
        self.lowPass:           tuple[int]  = lowPass           # low-pass for EEG/EMG in 11-500 Hz range. 

    def EEG1(self):
        return(self.lowPass[0])

    def EEG2(self):
        return(self.lowPass[1])

    def EEG3_EMG(self):
        return(self.lowPass[2])


# ##########################################################################################


class Params_8401HR(Params_Interface) :
    pass
    




# ##########################################################################################


class Params_8229(Params_Interface) :
    pass



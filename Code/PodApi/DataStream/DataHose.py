from PodApi.Devices import Pod

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"


class Valve : 
    def __init__(self, 
                 podDevice: Pod, 
                 streamCmd: str|int, 
                 streamPldStart: int|bytes|tuple[int|bytes]|None, 
                 streamPldStop: int|bytes|tuple[int|bytes]|None) -> None:
        
        podDevice._commands.ValidateCommand(streamCmd,streamPldStart)
        podDevice._commands.ValidateCommand(streamCmd,streamPldStop)
        
        self.podDevice : Pod = podDevice
        streamCmd: str|int = streamCmd
        streamPldStart : int|bytes|tuple[int|bytes] = streamPldStart
        streamPldStop  : int|bytes|tuple[int|bytes] = streamPldStop
        
        
    def Open():
        pass
    
    def Close():
        pass
                

class Hose : 
    
    def __init__(self, 
                 podDevice: Pod, 
                 streamCmd: str|int, 
                 streamPldStart: int|bytes|tuple[int|bytes], 
                 streamPldStop: int|bytes|tuple[int|bytes]) -> None:
        

        self.podDevice : Pod = podDevice
        
        if( podDevice._commands.DoesCommandExist(streamCmd) ) :
            self.streamCmd : str|int = streamCmd
        else : 
            raise Exception('[!] Command '+str(streamCmd)+' does not exist.')
        
from PodApi.Devices import Pod

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"


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
        
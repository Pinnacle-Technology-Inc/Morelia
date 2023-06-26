# local imports 
from BasicPodProtocol import POD_Basics

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class POD_8229(POD_Basics) : 

    def __init__(self, port: str|int, baudrate:int=19200) -> None :
        # initialize POD_Basics
        super().__init__(port, baudrate=baudrate) 
        # remove unimplemented commands 
        self._commands.RemoveCommand( 4) # ERROR
        self._commands.RemoveCommand( 5) # STATUS
        self._commands.RemoveCommand( 6) # STREAM
        self._commands.RemoveCommand(10) # SRATE
        self._commands.RemoveCommand(11) # BINARY
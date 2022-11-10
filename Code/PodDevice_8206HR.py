from BasicPodProtocol import POD_Basics
from PodCommands import POD_Commands

class POD_8206HR(POD_Basics) : 

    # ============ GLOBAL CONSTANTS ============    ========================================================================================================================

    # ============ DUNDER METHODS ============      ========================================================================================================================

    def __init__(self, port, baudrate=9600) :
        # initialize POD_Basics
        super().__init__(port, baudrate=baudrate) 
        # remove unimplemented commands 
        self.__commands.RemoveCommand(5)  # STATUS
        self.__commands.RemoveCommand(9)  # ID
        self.__commands.RemoveCommand(10) # SAMPLE RATE
        self.__commands.RemoveCommand(11) # BINARY
        # add device specific commands
        self.__commands.AddCommand(100, 'GET SAMPLE RATE',      0,                                      POD_Commands.U16()      )
        self.__commands.AddCommand(101, 'SET SAMPLE RATE',      POD_Commands.U16(),                     0                       )
        self.__commands.AddCommand(102, 'GET LOWPASS',          POD_Commands.U8(),                      POD_Commands.U16()      )
        self.__commands.AddCommand(103, 'SET LOWPASS',          POD_Commands.U8()+POD_Commands.U16(),   0                       )
        self.__commands.AddCommand(104, 'SET TTL OUT',          POD_Commands.U8()+POD_Commands.U8(),    0                       )
        self.__commands.AddCommand(105, 'GET TTL IN',           POD_Commands.U8(),                      POD_Commands.U8()       )
        self.__commands.AddCommand(106, 'GET TTL PORT',         0,                                      POD_Commands.U8()       )
        self.__commands.AddCommand(107, 'GET FILTER CONFIG',    0,                                      POD_Commands.U8()       )
        self.__commands.AddCommand(180, 'BINARY4 DATA ',        0,                                      POD_Commands.NoValue()  )

    # ============ STATIC METHODS ============      ========================================================================================================================

    # ============ PUBLIC METHODS ============      ========================================================================================================================

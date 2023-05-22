"""
POD_Commands manages a dictionary containing available commands for a POD device.
"""

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class POD_Commands : 

    # ============ GLOBAL CONSTANTS ============    ========================================================================================================================


    # index keys for self.__commands dict values 
    __NAME      : int = 0
    __ARGUMENTS : int = 1
    __RETURNS   : int = 2
    __BINARY    : int = 3

    # flag used to mark if self.__commands dict value has no real value 
    __NOVALUE : int = -1

    # number of hex characters for a given payload value (U=unsigned, #=bit)
    __U8  : int = 2
    __U16 : int = 2*__U8


    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self) -> None : 
        # contains allowed POD commands (basic set)
        self.__commands = POD_Commands.GetBasicCommands()


    # ============ STATIC METHODS ============  ========================================================================================================================


    @staticmethod
    def NoValue() -> int : 
        # returns the no value marker for commands dict 
        return(POD_Commands.__NOVALUE)

    @staticmethod
    def U8() -> int : 
        # returns the no value marker for commands dict 
        return(POD_Commands.__U8)

    @staticmethod
    def U16() -> int : 
        # returns the no value marker for commands dict 
        return(POD_Commands.__U16)

    @staticmethod
    def GetBasicCommands() -> dict[int,list[str|tuple[int]|bool]] : 
        # constants 
        U8 = POD_Commands.U8()
        NOVALUE = POD_Commands.NoValue()
        # basic standard POD commands 
        basics = { # key(command number) : value([command name, (number of argument ASCII hex chars), (number of return ASCII hex chars), binary flag ]), 
            0   : [ 'ACK',                  (0,),      (0,),          False   ],
            1   : [ 'NACK',                 (0,),      (0,),          False   ],
            2   : [ 'PING',                 (0,),      (0,),          False   ],
            3   : [ 'RESET',                (0,),      (0,),          False   ],
            4   : [ 'ERROR',                (0,),      (U8,),         False   ],
            5   : [ 'STATUS',               (0,),      (0,),          False   ],
            6   : [ 'STREAM',               (U8,),     (U8,),         False   ], 
            7   : [ 'BOOT',                 (0,),      (0,),          False   ],
            8   : [ 'TYPE',                 (0,),      (U8,),         False   ],
            9   : [ 'ID',                   (0,),      (0,),          False   ],
            10  : [ 'SAMPLE RATE',          (0,),      (0,),          False   ],
            11  : [ 'BINARY',               (0,),      (NOVALUE,),    True    ],  # No return bytes because the length depends on the message
            12  : [ 'FIRMWARE VERSION',     (0,),      (U8,U8,U8),    False   ]
        }
        # return dict of commands 
        return(basics)


    # ============ PUBLIC METHODS ============      ========================================================================================================================


    def GetCommands(self) -> dict[int, list[str|tuple[int]|bool]] :
        # returns dict containing commands 
        return(self.__commands)


    def RestoreBasicCommands(self) -> None : 
        # set commands to the basic command set 
        self.__commands = POD_Commands.GetBasicCommands()


    def AddCommand(self, commandNumber: int, commandName: str, argumentBytes: tuple[int], returnBytes: tuple[int], isBinary: bool) -> bool:
        # command number and name must not already exist 
        if(    self.DoesCommandExist(commandNumber)
            or self.DoesCommandExist(commandName)
        ):
            # return false to mark failed add 
            return(False)
        # add entry to dict 
        self.__commands[int(commandNumber)] = [str(commandName).upper(),tuple(argumentBytes),tuple(returnBytes),bool(isBinary)]
        # return true to mark successful add
        return(True)


    def RemoveCommand(self, cmd: int|str) -> bool :
        # return false if command is not in dict 
        if(not self.DoesCommandExist(cmd)): 
            return(False)
        # get command number 
        if(isinstance(cmd,str)):
            cmdNum = self.CommandNumberFromName(cmd)
        else: 
            cmdNum = cmd
        # remove entry in dict
        self.__commands.pop(cmdNum)
        # return true to mark that cmd was removed from dict
        return(True)


    def CommandNumberFromName(self, name: str) -> int|None : 
        # search through dict to find key 
        for key,val in self.__commands.items() :
            if(name == val[self.__NAME]) : 
                return(key)
        # no match
        return(None)


    def ArgumentHexChar(self, cmd: int|str) -> tuple[int]|None : 
        # search through dict to find matching entry  
        for key,val in self.__commands.items() :
            if(cmd == key or cmd == val[self.__NAME]) : 
                # return the number of hex characters (4 bits each) in the command argument 
                return(val[self.__ARGUMENTS])
        # no match
        return(None) 


    def ReturnHexChar(self, cmd: int|str) -> tuple[int]|None : 
        # search through dict to find matching entry  
        for key,val in self.__commands.items() :
            if(cmd == key or cmd == val[self.__NAME]) : 
                # return the number of hex characters (4 bits each) in the command return 
                return(val[self.__RETURNS])
        # no match
        return(None) 


    def IsCommandBinary(self, cmd: int|str) -> bool|None :
        # search through dict to find matching entry  
        for key,val in self.__commands.items() :
            if(cmd == key or cmd == val[self.__NAME]) : 
                # return true if the command is binary, false otherwise
                return(val[self.__BINARY])
        # no match
        return(None) 


    def DoesCommandExist(self, cmd: int|str) -> bool : 
        # check each command number and name to try to find match 
        for key,val in self.__commands.items() : 
            if(cmd==key or cmd==val[self.__NAME]):
                # set to true if match found 
                return(True)
        # return true if the command is in the command dict, false otherwise
        return(False)
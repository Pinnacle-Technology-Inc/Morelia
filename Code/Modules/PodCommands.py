"""
POD_Commands manages a dictionary containing available commands for a POD device.
"""

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__email__       = "sales@pinnaclet.com"
__date__        = "12/16/2022"

class POD_Commands : 

    # ============ GLOBAL CONSTANTS ============    ========================================================================================================================


    # index keys for self.__commands dict values 
    __NAME      = 0
    __ARGUMENTS = 1
    __RETURNS   = 2
    __BINARY    = 3

    # flag used to mark if self.__commands dict value has no real value 
    __NOVALUE = -1

    # number of bytes for a given payload value (U=unsigned, #=bit)
    __U8  = 2
    __U16 = 4


    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self) : 
        # contains allowed POD commands (basic set)
        self.__commands = POD_Commands.GetBasicCommands()


    # ============ STATIC METHODS ============  ========================================================================================================================


    @staticmethod
    def NoValue() : 
        # returns the no value marker for commands dict 
        return(POD_Commands.__NOVALUE)

    @staticmethod
    def U8() : 
        # returns the no value marker for commands dict 
        return(POD_Commands.__U8)

    @staticmethod
    def U16() : 
        # returns the no value marker for commands dict 
        return(POD_Commands.__U16)

    @staticmethod
    def GetBasicCommands() : 
        # constants 
        U8 = POD_Commands.U8()
        NOVALUE = POD_Commands.NoValue()
        # basic standard POD commands 
        basics = { # key(command number) : value([command name, (number of argument ascii bytes), (number of return bytes), binary flag ]), 
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


    def GetCommands(self):
        # returns dict containing commands 
        return(self.__commands)


    def RestoreBasicCommands(self) : 
        # set commands to the basic command set 
        self.__commands = POD_Commands.GetBasicCommands()


    def AddCommand(self,commandNumber,commandName,argumentBytes,returnBytes,isBinary):
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


    def RemoveCommand(self,cmd) :
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


    def CommandNumberFromName(self, name) : 
        # search through dict to find key 
        for key,val in self.__commands.items() :
            if(name == val[self.__NAME]) : 
                return(key)
        # no match
        return(None)


    def ArgumentBytes(self, cmd) : 
        # search through dict to find matching entry  
        for key,val in self.__commands.items() :
            if(cmd == key or cmd == val[self.__NAME]) : 
                # return the number of bytes in the command argument 
                return(val[self.__ARGUMENTS])
        # no match
        return(None) 


    def ReturnBytes(self,cmd) : 
        # search through dict to find matching entry  
        for key,val in self.__commands.items() :
            if(cmd == key or cmd == val[self.__NAME]) : 
                # return the number of bytes in the command return 
                return(val[self.__RETURNS])
        # no match
        return(None) 


    def IsCommandBinary(self, cmd):
        # search through dict to find matching entry  
        for key,val in self.__commands.items() :
            if(cmd == key or cmd == val[self.__NAME]) : 
                # return true if the command is binary, false otherwise
                return(val[self.__BINARY])
        # no match
        return(None) 


    def DoesCommandExist(self, cmd) : 
        # initialize to false
        isValidCmd = False
        # check each command number and name to try to find match 
        for key,val in self.__commands.items() : 
            if(cmd==key or cmd==val[self.__NAME]):
                # set to true if match found 
                isValidCmd = True
        # return true if the command is in the command dict, false otherwise
        return(isValidCmd)
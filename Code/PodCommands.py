

class POD_Commands : 

    # ============ GLOBAL CONSTANTS ============    ========================================================================================================================


    # index keys for self.__commands dict values 
    __NAME      = 0
    __ARGUMENTS = 1
    __RETURNS   = 2

    # flag used to mark if self.__commands dict value has no real value 
    __NOVALUE = -1

    # stores basic standard POD commands 
    __BASICCOMMANDS = { # key(command number) : value([command name, number of argument ascii bytes, number of return bytes]), 
            0   : [ 'ACK',                  0,      0               ],
            1   : [ 'NACK',                 0,      0               ],
            2   : [ 'PING',                 0,      0               ],
            3   : [ 'RESET',                0,      0               ],
            4   : [ 'ERROR',                0,      2               ],
            5   : [ 'STATUS',               0,      0               ],
            6   : [ 'STREAM',               2,      2               ], 
            7   : [ 'BOOT',                 0,      0               ],
            8   : [ 'TYPE',                 0,      2               ],
            9   : [ 'ID',                   0,      0               ],
            10  : [ 'SAMPLE RATE',          0,      0               ],
            11  : [ 'BINARY',               0,      __NOVALUE       ],  # No return bytes because the length depends on the message
            12  : [ 'FIRMWARE VERSION',     0,      6               ]
        }

    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self) : 
        # contains allowed POD commands (basic set)
        self.__commands = POD_Commands.__BASICCOMMANDS


    # ============ STATIC METHODS ============  ========================================================================================================================


    @staticmethod
    def GetNoValue() : 
        # returns the no value marker for commands dict 
        return(POD_Commands.__NOVALUE)


    @staticmethod
    def GetBasicCommands() : 
        return(POD_Commands.__BASICCOMMANDS)


    # ============ PUBLIC METHODS ============      ========================================================================================================================


    def GetCommands(self):
        # returns dict containing commands 
        return(self.__commands)


    def RestoreBasicCommands(self) : 
        # set commands to the basic command set 
        self.__commands = POD_Commands.__BASICCOMMANDS


    def AddCommand(self,commandNumber,commandName,argumentBytes,returnBytes):
        # command number and name must not already exist 
        if(    self.DoesCommandExist(commandNumber)
            or self.DoesCommandExist(commandName)
        ):
            # return false to mark failed add 
            return(False)
        # add entry to dict 
        self.__commands[int(commandNumber)] = [str(commandName).upper(),int(argumentBytes),int(returnBytes)]
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
                # return the number of bytes in the command return 
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
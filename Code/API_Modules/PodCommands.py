# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class POD_Commands : 
    """
    POD_Commands manages a dictionary containing available commands for a POD device.

    Attributes:
        __commands (dict[int,list[str|tuple[int]|bool]]): Dictionary containing the available commands for \
            a POD device. Each entry is formatted as { key(command number) : value([command name, number \
            of argument ASCII bytes, number of return bytes, binary flag ) }.
    """

    # ============ GLOBAL CONSTANTS ============    ========================================================================================================================


    __NAME      : int = 0
    """Class-level integer representing the index key for the command name for __commands \
    list values.
    """

    __ARGUMENTS : int = 1
    """Class-level integer representing the index key for the number of bytes in an \
    argument for __commands list values.
    """

    __RETURNS   : int = 2
    """Class-level integer representing the index key for the number of bytes in the \
    return for __commands list values.
    """

    __BINARY    : int = 3
    """Class-level integer representing the index key for the binary flag for __commands \
    list values.
    """

    # flag used to mark if self.__commands dict value has no real value 
    __NOVALUE : int = -1
    """Class-level integer used to mark when a list item in __commands means 'no value' \
    or is undefined.
    """

    __U8  : int = 2
    """Class-level integer representing the number of hexadecimal characters for an \
    unsigned 8-bit value.
    """

    __U16 : int = 2*__U8
    """Class-level integer representing the number of hexadecimal characters for an \
    unsigned 16-bit value.
    """

    __U32 : int = 4*__U8

    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self) -> None : 
        """Runs whan an instance is constructed. It sents the commands dictionary to the basic \
        command set.
        """
        # contains allowed POD commands (basic set)
        self.__commands : dict[int,list[str|tuple[int]|bool]] = POD_Commands.GetBasicCommands()


    # ============ STATIC METHODS ============  ========================================================================================================================


    @staticmethod
    def NoValue() -> int : 
        """Gets value of __NOVALUE.

        Returns:
            int: Value of __NOVALUE.
        """
        # returns the no value marker for commands dict 
        return(POD_Commands.__NOVALUE)

    @staticmethod
    def U8() -> int : 
        """Gets value of __U8.

        Returns:
            int: Value of __U8.
        """
        # returns the no value marker for commands dict 
        return(POD_Commands.__U8)

    @staticmethod
    def U16() -> int : 
        """Gets value of __U16.

        Returns:
            int: Value of __U16.
        """
        # returns the no value marker for commands dict 
        return(POD_Commands.__U16)
    
    @staticmethod
    def U32() -> int : 
        """Gets value of __U16.

        Returns:
            int: Value of __U16.
        """
        # returns the no value marker for commands dict 
        return(POD_Commands.__U32)
    

    @staticmethod
    def GetBasicCommands() -> dict[int,list[str|tuple[int]|bool]] : 
        """Creates a dictionary containing the basic POD command set (0,1,2,3,4,5,6,7,8,9,10,11,12).

        Returns:
            dict[int,list[str|tuple[int]|bool]]: Dictionary containing the available commands for this POD \
                device. Each entry is formatted as { key(command number) : value([command name, number of \
                argument ASCII bytes, number of return bytes, binary flag ) }.
        """
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
        """Gets the contents of the current command dictionary (__commands).

        Returns:
            dict[int, list[str|tuple[int]|bool]]: Dictionary containing the available commands for a POD \
                device. Each entry is formatted as { key(command number) : value([command name, number of \
                argument ASCII bytes, number of return bytes, binary flag ) }.
        """
        # returns dict containing commands 
        return(self.__commands)


    def RestoreBasicCommands(self) -> None : 
        """Sets the current commands (__commands) to the basic POD command set."""
        # set commands to the basic command set 
        self.__commands = POD_Commands.GetBasicCommands()


    def AddCommand(self, commandNumber: int, commandName: str, argumentBytes: tuple[int], returnBytes: tuple[int], isBinary: bool) -> bool:
        """Adds a command entry to the current commands dictionary (__commands) if the command does \
        not exist.

        Args:
            commandNumber (int): Integer of the command number.
            commandName (str): String of the command's name.
            argumentBytes (tuple[int]): Integer of the number of bytes in the argument.
            returnBytes (tuple[int]): Integer of the number of bytes in the return.
            isBinary (bool): Boolean flag to mark if the command is binary (True) or standard (False). 

        Returns:
            bool: True if the command was successfully added, False if the command could not be added \
                because it already exists.
        """
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
        """Removes the entry for a given command in __commands dictionary. 

        Args:
            cmd (int | str): integer command number or string command name. 

        Returns:
            bool: True if the command was successfully removed, False if the command does not exist. 
        """
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
        """Gets the command number from the command dictionary using the command's name.

        Args:
            name (str): string of the command's name.

        Returns:
            int|None: Integer representing the command number. If the command could not be found, \
                return None.
        """
        # search through dict to find key 
        for key,val in self.__commands.items() :
            if(name == val[self.__NAME]) : 
                return(key)
        # no match
        return(None)


    def ArgumentHexChar(self, cmd: int|str) -> tuple[int]|None : 
        """Gets the tuple for the number of hex characters in the argument for a given command.

        Args:
            cmd (int | str): integer command number or string command name. 

        Returns:
            tuple[int]|None: Tuple representing the number of bytes in the argument for cmd. If the \
                command could not be found, return None.
        """
        # search through dict to find matching entry  
        for key,val in self.__commands.items() :
            if(cmd == key or cmd == val[self.__NAME]) : 
                # return the number of hex characters (4 bits each) in the command argument 
                return(val[self.__ARGUMENTS])
        # no match
        return(None) 


    def ReturnHexChar(self, cmd: int|str) -> tuple[int]|None : 
        """Gets the tuple for the number of hex characters in the return for a given command.

        Args:
            cmd (int | str): integer command number or string command name. 

        Returns:
            tuple[int]|None: Tuple representing the number of hex characters in the return for cmd. If the \
                command could not be found, return None.
        """
        # search through dict to find matching entry  
        for key,val in self.__commands.items() :
            if(cmd == key or cmd == val[self.__NAME]) : 
                # return the number of hex characters (4 bits each) in the command return 
                return(val[self.__RETURNS])
        # no match
        return(None) 


    def IsCommandBinary(self, cmd: int|str) -> bool|None :
        """Gets the binary flag for a given command.

        Args:
            cmd (int | str): integer command number or string command name. 

        Returns:
            bool|None: Boolean flag that is True if the command is binary and False if standard. If the \
                command could not be found, return None.
        """
        # search through dict to find matching entry  
        for key,val in self.__commands.items() :
            if(cmd == key or cmd == val[self.__NAME]) : 
                # return true if the command is binary, false otherwise
                return(val[self.__BINARY])
        # no match
        return(None) 


    def DoesCommandExist(self, cmd: int|str) -> bool : 
        """Checks if a command exists in the __commands dictionary.

        Args:
            cmd (int | str): integer command number or string command name. 

        Returns:
            bool: True if the command exists, false otherwise.
        """
        # check each command number and name to try to find match 
        for key,val in self.__commands.items() : 
            if(cmd==key or cmd==val[self.__NAME]):
                # set to true if match found 
                return(True)
        # return true if the command is in the command dict, false otherwise
        return(False)
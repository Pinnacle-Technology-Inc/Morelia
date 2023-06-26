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


    __NAME : int = 0
    """Class-level integer representing the index key for the command name for __commands \
    list values.
    """

    __ARGUMENTS : int = 1
    """Class-level integer representing the index key for the number of bytes in an \
    argument for __commands list values.
    """

    __RETURNS : int = 2
    """Class-level integer representing the index key for the number of bytes in the \
    return for __commands list values.
    """

    __BINARY : int = 3
    """Class-level integer representing the index key for the binary flag for __commands \
    list values.
    """

    __DESCRIPTION : int = 4
    """Class-level integer representing the index key for the description for __commands \
    list values.
    """

    # flag used to mark if self.__commands dict value has no real value 
    __NOVALUE : int = -1
    """Class-level integer used to mark when a list item in __commands means 'no value' \
    or is undefined.
    """

    __U8 : int = 2
    """Class-level integer representing the number of hexadecimal characters for an \
    unsigned 8-bit value.
    """

    __U16 : int = 2*__U8
    """Class-level integer representing the number of hexadecimal characters for an \
    unsigned 16-bit value.
    """


    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self) -> None : 
        """Runs whan an instance is constructed. It sents the commands dictionary to the basic \
        command set.
        """
        self.__commands : dict[int,list[str|tuple[int]|bool]] = POD_Commands.GetBasicCommands()


    # ============ STATIC METHODS ============  ========================================================================================================================


    @staticmethod
    def NoValue() -> int : 
        """Gets value of __NOVALUE.

        Returns:
            int: Value of __NOVALUE.
        """
        return(POD_Commands.__NOVALUE)

    @staticmethod
    def U8() -> int : 
        """Gets value of __U8.

        Returns:
            int: Value of __U8.
        """
        return(POD_Commands.__U8)

    @staticmethod
    def U16() -> int : 
        """Gets value of __U16.

        Returns:
            int: Value of __U16.
        """
        return(POD_Commands.__U16)

    @staticmethod
    def GetBasicCommands() -> dict[int,list[str|tuple[int]|bool|str]] : 
        """Creates a dictionary containing the basic POD command set (0,1,2,3,4,5,6,7,8,9,10,11,12).

        Returns:
            dict[int,list[str|tuple[int]|bool|str]]: Dictionary containing the available commands for this POD \
                device. Each entry is formatted as { key(command number) : value([command name, number of \
                argument ASCII bytes, number of return bytes, binary flag, description) }.
        """
        # constants 
        U8  = POD_Commands.U8()
        U16 = POD_Commands.U16()
        NOVALUE = POD_Commands.NoValue()
        # basic standard POD commands 
        basics = { # key(command number) : value([command name, (number of argument ASCII hex chars), (number of return ASCII hex chars), binary flag, description]), 
            0  : [ 'ACK',               (0,),   (0,),        False,  'Deprecated in favor of responding with the command number received.'                    ],
            1  : [ 'NACK',              (0,),   (0,),        False,  'Used to indicate an unsupported command was received.'                                  ],
            2  : [ 'PING',              (0,),   (0,),        False,  'Basic ping command to check if a device is alive and communicating.'                    ],
            3  : [ 'RESET',             (0,),   (0,),        False,  'Causes the device to reset.  Devices also send this command upon bootup.'               ],
            4  : [ 'ERROR',             (0,),   (U8,),       False,  'Reports error codes; mostly unused.'                                                    ],
            5  : [ 'STATUS',            (0,),   (0,),        False,  'Reports status codes; mostly unused.'                                                   ],
            6  : [ 'STREAM',            (U8,),  (U8,),       False,  'Enables or disables streaming of binary packets on the device'                          ], 
            7  : [ 'BOOT',              (0,),   (0,),        False,  'Instructs the device to enter bootload mode.'                                           ],
            8  : [ 'TYPE',              (0,),   (U8,),       False,  'Gets the device type. Often unused due to USB descriptor duplicating this function.'    ],
            9  : [ 'ID',                (0,),   (0,),        False,  'ID number for the device. Often unused due to USB descriptor duplicating this function.'],
            10 : [ 'SAMPLE RATE',       (0,),   (0,),        False,  'Gets the sample rate of the device.  Often unused in favor of just setting it.'         ],
            11 : [ 'BINARY',            (0,),   (NOVALUE,),   True,  'Indicates a binary packet.'                                                             ],  # No return bytes because the length depends on the message
            12 : [ 'FIRMWARE VERSION',  (0,),   (U8,U8,U16), False,  'Returns firmware version of the device.'                                                ]
        }
        # return dict of commands 
        return(basics)


    # ============ PUBLIC METHODS ============      ========================================================================================================================


    def GetCommands(self) -> dict[int, list[str|tuple[int]|bool|str]] :
        """Gets the contents of the current command dictionary (__commands).

        Returns:
            dict[int, list[str|tuple[int]|bool|str]]: Dictionary containing the available commands for a POD \
                device. Each entry is formatted as { key(command number) : value([command name, number of \
                argument ASCII bytes, number of return bytes, binary flag, description) }.
        """
        # returns dict containing commands 
        return(self.__commands)


    def RestoreBasicCommands(self) -> None : 
        """Sets the current commands (__commands) to the basic POD command set."""
        # set commands to the basic command set 
        self.__commands = POD_Commands.GetBasicCommands()


    def AddCommand(self, commandNumber: int, commandName: str, argumentBytes: tuple[int], returnBytes: tuple[int], isBinary: bool, description: str) -> bool:
        """Adds a command entry to the current commands dictionary (__commands) if the command does \
        not exist.

        Args:
            commandNumber (int): Integer of the command number.
            commandName (str): String of the command's name.
            argumentBytes (tuple[int]): Integer of the number of bytes in the argument.
            returnBytes (tuple[int]): Integer of the number of bytes in the return.
            isBinary (bool): Boolean flag to mark if the command is binary (True) or standard (False). 
            description (str): String description of the command.

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
        self.__commands[int(commandNumber)] = [str(commandName).upper(),tuple(argumentBytes),tuple(returnBytes),bool(isBinary),str(description)]
        # return true to mark successful add
        return(True)


    def RemoveCommand(self, cmd: int|str) -> bool :
        """Removes the entry for a given command in __commands dictionary. 

        Args:
            cmd (int | str): Integer command number or string command name. 

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
            name (str): String of the command's name.

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
            cmd (int | str): Integer command number or string command name. 

        Returns:
            tuple[int]|None: Tuple representing the number of bytes in the argument for cmd. If the \
                command could not be found, return None.
        """
        return( self.Search(cmd, self.__ARGUMENTS) )


    def ReturnHexChar(self, cmd: int|str) -> tuple[int]|None : 
        """Gets the tuple for the number of hex characters in the return for a given command.

        Args:
            cmd (int | str): Integer command number or string command name. 

        Returns:
            tuple[int]|None: Tuple representing the number of hex characters in the return for cmd. If the \
                command could not be found, return None.
        """
        return( self.Search(cmd, self.__RETURNS) )


    def IsCommandBinary(self, cmd: int|str) -> bool|None :
        """Gets the binary flag for a given command.

        Args:
            cmd (int | str): Integer command number or string command name. 

        Returns:
            bool|None: Boolean flag that is True if the command is binary and False if standard. If the \
                command could not be found, return None.
        """
        return( self.Search(cmd, self.__BINARY) )


    def Description(self, cmd: int|str) -> str|None : 
        """Gets the description for a given command.

        Args:
            cmd (int | str): Integer command number or string command name. 

        Returns:
            str|None: String description for the command. If the command could not be found, \
                return None.
        """
        return( self.Search(cmd, self.__DESCRIPTION) )



    def DoesCommandExist(self, cmd: int|str) -> bool : 
        """Checks if a command exists in the __commands dictionary.

        Args:
            cmd (int | str): Integer command number or string command name. 

        Returns:
            bool: True if the command exists, false otherwise.
        """
        return( self.Search(cmd) )


    def Search(self, cmd: int|str, idx: int = None) -> str|tuple[int]|bool|str|None :
        """Searches the __commands dictionary for the command. 

        Args:
            cmd (int | str): Integer command number or string command name. 
            idx (int, optional): Index for the desired value in the command information list. \
                Defaults to None.

        Returns:
            str|tuple[int]|bool|str|None: If an idx was given, this returns the idx value of the \
                command information list if the command was found (None otherwise). If no idx is \
                given, this returns true if the command is found (False otherwise).
        """

        # search through dict to find matching entry  
        for key,val in self.__commands.items() :
            if(cmd == key or cmd == val[self.__NAME]) : 
                if(idx != None) :   return(val[idx])
                else:               return(True)
        # no match
        if(idx !=None) :    return(None) 
        else:               return(False)
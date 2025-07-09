# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert", "Sree Kondi"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class CommandSet : 
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
    __NO_VALUE : int = -1
    """Class-level integer used to mark when a list item in __commands means 'no value' \
    or is undefined.
    """

    __UINT8 : int = 2
    """Class-level integer representing the number of hexadecimal characters for an \
    unsigned 8-bit value.
    """

    __UINT16 : int = 2*__UINT8
    """Class-level integer representing the number of hexadecimal characters for an \
    unsigned 16-bit value.
    """

    __UINT32 : int = 4*__UINT8
    """Class-level integer representing the number of hexadecimal characters for an \
    unsigned 32-bit value.
    """
    
    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self) -> None : 
        """Runs whan an instance is constructed. It sents the commands dictionary to the basic \
        command set.
        """
        self.__commands : dict[int,list[str|tuple[int]|bool]] = CommandSet.get_basic_commands()


    # ============ STATIC METHODS ============  ========================================================================================================================


    @staticmethod
    def no_value() -> int : 
        """Gets value of __NO_VALUE.

        Returns:
            int: Value of __NO_VALUE.
        """
        return(CommandSet.__NO_VALUE)

    @staticmethod
    def get_uint8 () -> int : 
        """Gets value of __UINT8.

        Returns:
            int: Value of __UINT8.
        """
        return(CommandSet.__UINT8)

    @staticmethod
    def get_uint16() -> int : 
        """Gets value of __UINT16.

        Returns:
            int: Value of __UINT16.
        """
        return(CommandSet.__UINT16)
    
    @staticmethod
    def get_uint32() -> int : 
        """Gets value of __UINT32.

        Returns:
            int: Value of __UINT32.
        """
        # returns the no value marker for commands dict 
        return(CommandSet.__UINT32)
    

    @staticmethod
    def get_basic_commands() -> dict[int,list[str|tuple[int]|bool|str]] : 
        """Creates a dictionary containing the basic POD command set (0,1,2,3,4,5,6,7,8,9,10,11,12).

        Returns:
            dict[int,list[str|tuple[int]|bool|str]]: Dictionary containing the available commands for this POD \
                device. Each entry is formatted as { key(command number) : value([command name, number of \
                argument ASCII bytes, number of return bytes, binary flag, description) }.
        """
        # constants 
        UINT8  = CommandSet.get_uint8()
        UINT16 = CommandSet.get_uint16()
        NO_VALUE = CommandSet.no_value()
        # basic standard POD commands 
        basics = { # key(command number) : value([command name, (number of argument ASCII hex chars), (number of return ASCII hex chars), binary flag, description]), 
            0  : [ 'ACK',               (0,),   (0,),        False,  'Deprecated in favor of responding with the command number received.'                    ],
            1  : [ 'NACK',              (0,),   (0,),        False,  'Used to indicate an unsupported command was received.'                                  ],
            2  : [ 'PING',              (0,),   (0,),        False,  'Basic ping command to check if a device is alive and communicating.'                    ],
            3  : [ 'RESET',             (0,),   (0,),        False,  'Causes the device to reset.  Devices also send this command upon bootup.'               ],
            4  : [ 'ERROR',             (0,),   (UINT8,),       False,  'Reports error codes; mostly unused.'                                                    ],
            5  : [ 'STATUS',            (0,),   (0,),        False,  'Reports status codes; mostly unused.'                                                   ],
            6  : [ 'STREAM',            (UINT8,),  (UINT8,),       False,  'Enables or disables streaming of binary packets on the device'                          ], 
            7  : [ 'BOOT',              (0,),   (0,),        False,  'Instructs the device to enter bootload mode.'                                           ],
            8  : [ 'TYPE',              (0,),   (UINT8,),       False,  'Gets the device type. Often unused due to USB descriptor duplicating this function.'    ],
            9  : [ 'ID',                (0,),   (0,),        False,  'ID number for the device. Often unused due to USB descriptor duplicating this function.'],
            10 : [ 'SAMPLE RATE',       (0,),   (0,),        False,  'Gets the sample rate of the device.  Often unused in favor of just setting it.'         ],
            11 : [ 'BINARY',            (0,),   (NO_VALUE,),   True,  'Indicates a binary packet.'                                                             ],  # No return bytes because the length depends on the message
            12 : [ 'FIRMWARE VERSION',  (0,),   (UINT8,UINT8,UINT16), False,  'Returns firmware version of the device.'                                                ],
            13 : [ 'SET ID',            (UINT16,), (0,),        False,  'Sets the System ID read from command 9'],
            14 : [ 'SAVE SETTINGS',     (UINT8,),  (0,),        False,  'Instructs the system to save its settings in EEPROM']
        }
        # return dict of commands 
        return(basics)

    # ============ PUBLIC METHODS ============      ========================================================================================================================


    def get_commands(self) -> dict[int, list[str|tuple[int]|bool|str]] :
        """Gets the contents of the current command dictionary (__commands).

        Returns:
            dict[int, list[str|tuple[int]|bool|str]]: Dictionary containing the available commands for a POD \
                device. Each entry is formatted as { key(command number) : value([command name, number of \
                argument ASCII bytes, number of return bytes, binary flag, description) }.
        """
        # returns dict containing commands 
        return(self.__commands)


    def restore_basic_commands(self) -> None : 
        """Sets the current commands (__commands) to the basic POD command set."""
        # set commands to the basic command set 
        self.__commands = CommandSet.get_basic_commands()


    def add_command(self, command_number: int, command_name: str, argument_bytes: tuple[int], return_bytes: tuple[int], is_binary: bool, description: str) -> bool:
        """Adds a command entry to the current commands dictionary (__commands) if the command does \
        not exist.

        Args:
            command_number (int): Integer of the command number.
            command_name (str): String of the command's name.
            argument_bytes (tuple[int]): Integer of the number of bytes in the argument.
            return_bytes (tuple[int]): Integer of the number of bytes in the return.
            is_binary (bool): Boolean flag to mark if the command is binary (True) or standard (False). 
            description (str): String description of the command.

        Returns:
            bool: True if the command was successfully added, False if the command could not be added \
                because it already exists.
        """
        # command number and name must not already exist 
        if(    self.does_command_exist(command_number)
            or self.does_command_exist(command_name)
        ):
            # return false to mark failed add 
            return(False)
        # add entry to dict 
        self.__commands[int(command_number)] = [str(command_name).upper(),tuple(argument_bytes),tuple(return_bytes),bool(is_binary),str(description)]
        # return true to mark successful add
        return(True)


    def remove_command(self, cmd: int|str) -> bool :
        """Removes the entry for a given command in __commands dictionary. 

        Args:
            cmd (int | str): Integer command number or string command name. 

        Returns:
            bool: True if the command was successfully removed, False if the command does not exist. 
        """
        # return false if command is not in dict 
        if(not self.does_command_exist(cmd)): 
            return(False)
        # get command number 
        if(isinstance(cmd,str)):
            cmd_num = self.command_number_from_name(cmd)
        else: 
            cmd_num = cmd
        # remove entry in dict
        self.__commands.pop(cmd_num)
        # return true to mark that cmd was removed from dict
        return(True)


    def command_number_from_name(self, name: str) -> int|None : 
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


    def argument_hex_char(self, cmd: int|str) -> tuple[int]|None : 
        """Gets the tuple for the number of hex characters in the argument for a given command.

        Args:
            cmd (int | str): Integer command number or string command name. 

        Returns:
            tuple[int]|None: Tuple representing the number of bytes in the argument for cmd. If the \
                command could not be found, return None.
        """
        return( self.search(cmd, self.__ARGUMENTS) )


    def return_hex_char(self, cmd: int|str) -> tuple[int]|None : 
        """Gets the tuple for the number of hex characters in the return for a given command.

        Args:
            cmd (int | str): Integer command number or string command name. 

        Returns:
            tuple[int]|None: Tuple representing the number of hex characters in the return for cmd. If the \
                command could not be found, return None.
        """
        return( self.search(cmd, self.__RETURNS) )


    def is_command_binary(self, cmd: int|str) -> bool|None :
        """Gets the binary flag for a given command.

        Args:
            cmd (int | str): Integer command number or string command name. 

        Returns:
            bool|None: Boolean flag that is True if the command is binary and False if standard. If the \
                command could not be found, return None.
        """
        return( self.search(cmd, self.__BINARY) )


    def description(self, cmd: int|str) -> str|None : 
        """Gets the description for a given command.

        Args:
            cmd (int | str): Integer command number or string command name. 

        Returns:
            str|None: String description for the command. If the command could not be found, \
                return None.
        """
        return( self.search(cmd, self.__DESCRIPTION) )



    def does_command_exist(self, cmd: int|str) -> bool : 
        """Checks if a command exists in the __commands dictionary.

        Args:
            cmd (int | str): Integer command number or string command name. 

        Returns:
            bool: True if the command exists, false otherwise.
        """
        return( self.search(cmd) )


    def search(self, cmd: int|str, idx: int = None) -> str|tuple[int]|bool|str|None :
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
        
        
    def validate_command(self, cmd: str|int, pld: int|bytes|tuple[int|bytes]|None=None) : 
        """Raises an exception if the command and its payload are invalid for this POD device. 

        Args:
            cmd (str | int): Command name or number.
            pld (int | bytes | tuple[int | bytes] | None, optional): Standard command packet payload. Defaults to None.

        Raises:
            Exception: Command '+str(cmd)+' does not exist.
            Exception: This command does not take a payload.
            Exception: This command requires a payload.
            Exception: Command needs more than one argument in the payload. Use a tuple of values.
            Exception: Payload must have '+str(sum(args))+' bytes.
            Exception: Payload must have '+str(len(args))+' integer items in the tuple.
            Exception: Bytes in the payload are the wrong sizes. The sizes must be '+str(args)+'.'
            Exception: The payload tuple must only contain int or bytes items.
            Exception: Payload is of incorrect type. It must be an int, bytes, or tuple of int/bytes.
        """
        
        # check if command exists first 
        if( not self.does_command_exist(cmd) ) :
            raise Exception('[!] Command '+str(cmd)+' does not exist.')

        # get argument lengths  
        args: tuple[int] = self.argument_hex_char(cmd)
        
        # check if no payload is needed
        if(sum(args) == 0) : 
            if(pld == None) : 
                return
            raise Exception('[!] This command does not take a payload.')
        
        # check type of payload 
        match pld : 
            case None : 
                raise Exception('[!] This command requires a payload.')
            
            case int() : 
                # pld has only one argument 
                if(len(args) != 1 ) :
                    raise Exception('[!] Command needs more than one argument in the payload. Use a tuple of values.')
                
            case bytes() : 
                if( len(pld) != sum(args)) :
                    raise Exception('[!] Payload must have '+str(sum(args))+' bytes.')
                
            case tuple() : 
                # check lengths 
                if(len(pld) != len(args)) : 
                    raise Exception('Payload must have '+str(len(args))+' integer items in the tuple.')  
                # check each item in the payload tuple
                for i in range(len(pld)) : 
                    if(isinstance(pld[i], bytes) and len(pld[i])!=args[i]) : 
                        raise Exception('[!] Bytes in the payload are the wrong sizes. The sizes must be '+str(args)+'.')
                    elif(not isinstance(pld[i],int)) : 
                        raise Exception('[!] The payload tuple must only contain int or bytes items.')
                    
            case _ :
                raise Exception('[!] Payload is of incorrect type. It must be an int, bytes, or tuple of int/bytes.')

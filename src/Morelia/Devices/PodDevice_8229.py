# enviornment imports 
from datetime import datetime

# local imports 
from Morelia.Devices import Pod
from Morelia.Commands import CommandSet
from Morelia.packet import ControlPacket
import Morelia.packet.conversion as conv

from functools import partial

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert", "James Hurd"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Pod8229(Pod) : 
    """POD8229 handles communication with a 8229 POD device.

    :param port: Serial port to be opened. Used when initializing the COM_io instance.
    :param baudrate: Integer baud rate of the opened serial port. Used when initializing the COM_io instance. Defaults to 19200.
    :param device_name: Virtual name used to identify device.
    """


    def __init__(self, port: str|int, baudrate:int=19200, device_name: str | None = None) -> None :
        """Runs when an instance is constructed. It runs the parent's initialization. Then it updates \
        the _commands to contain the appropriate command set for an 8229 POD device. 
        """
        # initialize POD_Basics
        super().__init__(port, baudrate=baudrate, device_name=device_name) 
        # get constants for adding commands 
        U8  = Pod.GetU(8)
        U16 = Pod.GetU(16)
        NOVALUE = Pod.GetU(0)
        # remove unimplemented commands 
        self._commands.RemoveCommand( 4) # ERROR
        self._commands.RemoveCommand( 5) # STATUS
        self._commands.RemoveCommand( 6) # STREAM
        self._commands.RemoveCommand(10) # SRATE
        self._commands.RemoveCommand(11) # BINARY
        # add device specific commands
        self._commands.AddCommand(128, 'SET MOTOR DIRECTION',   (U16,),                 (U16,),                 False, 'Sets motor direction, 0 for clockwise and 1 for counterclockwise.  Returns value set.')
        self._commands.AddCommand(129, 'GET MOTOR DIRECTION',   (0,),                   (U16,),                 False, 'Returns motor direction value.')
        self._commands.AddCommand(132, 'SET MODE',              (U8,),                  (U8,),                  False, 'Sets the current system mode - 0 = Manual, 1 = PC Control, 2 = Internal Schedule.  Returns the current mode.')
        self._commands.AddCommand(133, 'GET MODE',              (0,),                   (U8,),                  False, 'Gets the current system mode.')
        self._commands.AddCommand(136, 'SET MOTOR SPEED',       (U16,),                 (U16,),                 False, 'Sets motor speed as a percentage, 0-100.  Replies with PREVIOUS value.')
        self._commands.AddCommand(137, 'GET MOTOR SPEED',       (0,),                   (U16,),                 False, 'Gets the motor speed as a percentage, 0-100.')
        self._commands.AddCommand(140, 'SET TIME',              (U8,U8,U8,U8,U8,U8,U8), (U8,U8,U8,U8,U8,U8,U8), False, 'Sets the RTC time.  Format is (Seconds, Minutes, Hours, Day, Month, Year (without century, so 23 for 2023), Weekday).  Weekday is 0-6, with Sunday being 0.  Binary Coded Decimal. Returns current time.  Note that the the seconds (and sometimes minutes field) can rollover during execution of this command and may not match what you sent.')
        self._commands.AddCommand(141, 'SET DAY SCHEDULE',      (U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8), # ( U8, U8 x 24 )
                                                                                        (0,),                   False, 'Sets the schedule for the day.  U8 day, followed by 24 hourly schedule values.  MSb in each byte is a flag for motor on (1) or off (0), and the remaining 7 bits are the speed (0-100).')
        self._commands.AddCommand(142, 'GET DAY SCHEDULE',      (U8,),                  (U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8), # ( U8 x 24 )
                                                                                                                False, 'Gets the schedule for the selected week day (0-6 with 0 being Sunday).')
        self._commands.AddCommand(144, 'SET REVERSE PARAMS',    (U16,U16),              (0,),                   False, 'Sets (Base Time, Variable Time) for random reverse in seconds.  The random reverse time will be base time + a random value in Variable Time range.')
        self._commands.AddCommand(145, 'GET REVERSE PARAMS',    (0,),                   (U16,U16),              False, 'Gets the base and variable times for random reverse, in seconds.')
        self._commands.AddCommand(146, 'SET MOTOR STATE',       (U16,),                 (U16,),                 False, 'Sets whether the motor is on or off.  1 for On, 0 for Off. Returns the PREVIOUS motor state.')
        self._commands.AddCommand(147, 'GET MOTOR STATE',       (0,),                   (U16,),                 False, 'Gets the motor state.')
        self._commands.AddCommand(149, 'SET ID',                (U16,),                 (0,),                   False, 'Sets the system ID displayed on the LCD.')
        self._commands.AddCommand(150, 'SET RANDOM REVERSE',    (U8,),                  (0,),                   False, 'Enables or Disables Random Reverse function.  0 = disabled, Non-Zero = enabled.')
        self._commands.AddCommand(151, 'GET RANDOM REVERSE',    (0,),                   (U8,),                  False, 'Reads the Random Reverse function.  0 = disabled, non-zero = enabled.')
        # recieved only commands below vvv 
        self._commands.AddCommand(143, 'REVERSE TIME EVENT',    (0,),                   (U16,),                 False, 'Indicates the bar has just reveresed.  Returns the time in seconds until the next bar reversal.')
        self._commands.AddCommand(200, 'LCD SET MOTOR STATE',   (NOVALUE,),             (U16,),                 False, 'Indicates that the motor state has been changed by the LCD.  1 for On, 0 for Off.')
        self._commands.AddCommand(201, 'LCD SET MOTOR SPEED',   (NOVALUE,),             (U16,),                 False, 'Indicates the motor speed has been changed by the LCD.  0-100 as a percentage.')
        self._commands.AddCommand(202, 'LCD SET DAY SCHEDULE',  (NOVALUE,),             (U8,U8,U8,U8),          False, 'Indicates the LCD has changed the day schedule.  Byte 3 is weekday, Byte 2 is hours 0-7, Byte 3 is hours 8-15, and byte is hours 16-23.  Each bit represents the motor state in that hour, 1 for on and 0 for off.  Speed is whatever the current motor speed is.')
        self._commands.AddCommand(204, 'LCD SET MODE',          (NOVALUE,),             (U16,),                 False, 'Indicates the mode has been changed by the display.  0 = Manual, 1 = PC Control, 2 = Internal Schedule.')

        # Function used to decode payload of recieved control packets.
        def decode_payload(cmd_number: int, payload: bytes) -> tuple:
            match cmd_number:
                case 140:
                    return Pod8229._Custom140SETTIME(ControlPacket.decode_payload_from_cmd_set(self._commands, cmd_number, payload))

                case 141:
                    return Pod8229.DecodeDayAndSchedule(payload)

                case 142:
                    return Pod8229.DecodeDaySchedule(payload)

                case 202:
                    return Pod8229.DecodeLCDSchedule(payload)

                case _:
                    return ControlPacket.decode_payload_from_cmd_set(self._commands, cmd_number, payload)
        
        # Function used to construct recieved control packets from raw data.
        self._control_packet_factory = partial(ControlPacket, decode_payload)


    @staticmethod
    def GetCurrentTime() -> tuple[int] : 
        """Gets a tuple to use as the argument for command #140 SET TIME containing values for the current time. 

        :return: Tuple of 7 integer values. The format is (Seconds, Minutes, Hours, Day, Month, Year \
                (without century, so 23 for 2023), Weekday (0 for Sunday))
        """
        now = datetime.now()
        # Format is (Seconds, Minutes, Hours, Day, Month, Year (without century, so 23 for 2023), Weekday).
        arg = ( now.second, now.minute, now.hour, now.day, now.month, 
            int(now.strftime('%y')), # gets the year without the century 
            int(now.strftime('%w')) ) # Weekday is 0-6, with Sunday being 0.
        return(arg)

    @staticmethod
    def BuildSetDayScheduleArgument(day: str|int, hours: list|tuple[bool|int], speed: int|list|tuple[int]) -> tuple[int] :
        """Appends the day of the week code to the front of the encoded hourly schedule. this tuple is \
        formatted to be used as the #141 ``SET DAY SCHEDULE`` argument.

        :param day: Day of the week. Can be either the name of the day (i.e. Sunday, Monday, etc.) \
            or the 0-6 day code (0 for Sunday increacing to 6 for Saturday). 
        :param hours: Array of 24 items. The value is 1 for motor on and 0 for motor off.
        :param speed: Speed of the motor (0-100). This is an integer of all hours are the same speed. \
            If there are multiple speeds, this should be an array of 24 items.
        
        :return: Argument to pass with packet for ``SET DAY SCHEDULE``.
        """
        # get good value
        validDay: int = Pod8229._Validate_Day(day)
        # get encoded schedule
        encodedSched: list = Pod8229.CodeDaySchedule(hours,speed)
        # prepend the day to the schedule  
        return( tuple( [validDay]+encodedSched ) )


    @staticmethod
    def CodeDaySchedule(hours: list|tuple[bool|int], speed: int|list|tuple[int]) -> list[int] : 
        """Bitmasks the day schedule to encode the motor on/off status and the motor speed. Use this \
        for getting the command #141 ``SET DAY SCHEDULE`` U8x24 argument component.

        :param hours: Array of 24 items. The value is 1 for motor on and 0 for motor off.
        :param speed: Speed of the motor (0-100). This is an integer of all hours are the same speed. If there are multiple speeds, this should be an array of 24 items.

        :return: List of 24 integer items. The msb is the motor on/off flag and the remaining 7 bits are the speed.
        """
        # get good values 
        validHours = Pod8229._Validate_Hours(hours)
        validSpeed = Pod8229._Validate_Speed(speed) 
        # modify bits of each hour 
        schedule = [0] * 24
        for i in range(24) : 
            # msb is a flag for motor on (1) or off (0), and the remaining 7 bits are the speed (0-100)
            schedule[i] = ( validHours[i] << 7 ) | validSpeed[i]
        # return tuple that works as an argument for command #141 'SET DAY SCHEDULE'
        return( list(schedule) )

    @staticmethod
    def DecodeDaySchedule(schedule: bytes) -> dict[str,int|tuple[int]] :
        """Interprets the return bytes from the command #142 'GET DAY SCHEDULE'.

        :param schedule: 24 byte long bitstring with one U8 per hour in a day.

        :return: Dictionary with 'Hour' as a tuple of 24 0/1 values (0 is motor off and \
                1 is motor on) and 'Speed' as the motor speed (0-100). If the motor speed is the same \
                every hour, 'Speed' will be an integer; otherwise, 'Speed' will be a tuple of 24 items.
        """
        # use this for getting the command #argument 
        # check for valid arguments 
        validSchedule = Pod8229._Validate_Schedule(schedule, 24)
        # decode each hour
        hours  = [None] * 24
        speeds = [None] * 24
        for i in range(24) : 
            thisHr = validSchedule[2*i:2*i+2]
            # msb in each byte is a flag for motor on (1) or off (0)
            hours[i]  = conv.ascii_bytes_to_int_split(thisHr, 8, 7) 
            # remaining 7 bits are the speed (0-100)
            speeds[i] = conv.ascii_bytes_to_int_split(thisHr, 7, 0) 
        # check if all speeds are the same 
        if(len(set(speeds)) == 1) : 
            # speeds has all identical elements
            speeds = speeds[0]
        else : 
            speeds = tuple(speeds)
        # return hour and speeds 
        return({ 
            'Hour'  : tuple(hours), 
            'Speed' : speeds
        })
    
    
    @staticmethod
    def DecodeDayAndSchedule(dayschedule: bytes) -> tuple[int, dict[str,int|tuple[int]]]: 
        """Decode the packet payload returned by the ``SET DAY SCHEDULE``.

        :param dayschedule: Raw payload of packet.

        :returns: Tupke containg day and schedule for day.
        """
        U8 = Pod8229.GetU(8)
        day = conv.ascii_bytes_to_int(dayschedule[:U8])
        schedule = Pod8229.DecodeDaySchedule(dayschedule[U8:])
        return (day, schedule)
        
        
    @staticmethod
    def DecodeLCDSchedule(schedule: bytes) -> dict[str,str|list[int]] : 
        """Interprets the return bytes from the command #202 'LCD SET DAY SCHEDULE'.

        :param schedule: 4 Byte long bitstring. Byte 3 is weekday, Byte 2 is hours 0-7, Byte 1 is hours 8-15, and byte 0 is hours 16-23. 

        :return: Dictionary with Day as the day of the week, and Hours \
                containing a list of 24 0/1 values (one for each hour). Each bit represents the \
                motor state in that hour, 1 for on and 0 for off.
        """
        # check for valid arguments 
        validSchedule = Pod8229._Validate_Schedule(schedule, 4)
        # Byte 3 is weekday, Byte 2 is hours 0-7, Byte 1 is hours 8-15, and byte 0 is hours 16-23. 
        day = Pod8229.DecodeDayOfWeek( conv.ascii_bytes_to_int( validSchedule[0:2] ) )
        hourBytes = validSchedule[2:]
        # Get each hour bit 
        hours = []
        topBit = Pod.GetU(8) * 3 * 4 # (hex chars per U8) * (number of U8s) * (bits per hex char)
        while(topBit > 0 ) : 
            hours.append( conv.ascii_bytes_to_int_split( hourBytes, topBit, topBit-1))
            topBit -= 1
        # return decoded LCD SET DAY SCHEDULE value
        return{'Day' : day, 'Hours' : hours} # Each bit represents the motor state in that hour, 1 for on and 0 for off.


    @staticmethod
    def CodeDayOfWeek(day : str) -> int :
        """Converts the day of the week to an integer code understandable by the POD device. The day \
        is determined by the first 1-2 characters of the string, which supports multiple abbreviations \
        for days of the week.  

        :param day: Day of the week.

        :return: Code for the day of the week. Values are 0-6, with 0 for Saturday, 1 for Monday, ..., \
                and 6 for Saturday.
        """
        # Weekday is 0-6, with Sunday being 0
        match str(day).lower()[:1] : 
            case 'm'  : return(1) # monday
            case 'w'  : return(3) # wednesday 
            case 'f'  : return(5) # friday         
        match str(day).lower()[:2] : 
            case 'su' : return(0) # sunday
            case 'tu' : return(2) # tuesday
            case 'th' : return(4) # thursday
            case 'sa' : return(6) # saturday
        raise Exception('[!] Invalid day of the week: '+str(day))  
    

    @staticmethod
    def DecodeDayOfWeek(day: int) -> str :
        """Converts the integer code for a day of the week to a human-readable string. 

        :param day: Day of the week code must be 0-6.

        :return: Day of the week ('Sunday', 'Monday', etc.).
        """
        # Weekday is 0-6, with Sunday being 0
        match int(day):
            case 0 : return('Sunday')
            case 1 : return('Monday')
            case 2 : return('Tuesday')
            case 3 : return('Wednesday')
            case 4 : return('Thursday')
            case 5 : return('Friday')
            case 6 : return('Saturday')
            case _ : Exception('[!] Day of the week code must be 0-6.')  



    def WritePacket(self, cmd: str|int, payload:int|bytes|tuple[int|bytes]=None) -> ControlPacket :
        """Builds a POD packet and writes it to the POD device. 

        :param cmd: Command number.
        :param payload: (int | bytes | tuple[int | bytes], optional): None when there is no payload. If there \
                is a payload, set to an integer value, bytes string, or tuple. Defaults to None.

        :return: Packet that was written to the POD device.

        :meta private:
        """
        # check for commands with special encoding
        if(cmd == 140 or cmd == 'SET TIME') : 
            packet: ControlPacket = super().WritePacket(cmd,tuple([self._CodeDecimalAsHex(x) for x in payload ]))
        else :
            packet: ControlPacket = super().WritePacket(cmd,payload)

        # returns packet object
        return(packet)

    
    @staticmethod
    def _CodeDecimalAsHex(val: int) -> int : 
        """Builds an integer that equals the val argument when converted into hexadecimal. \
        All integers are converted to hexadecimal ASCII encoded bytes. Some commands \
        (i.e. 8229 #140) need decimal ASCII encoded bytes; to do this, give the return \
        value of _CodeDecimalAsHex() as the payload. Example: I want a number that is \
        equal to 16 in hex. 1*16^1 + 6*16^0 = 22. Calling _CodeDecimalAsHex(16) will \
        return 22.

        Args:
            val (int): Unsigned integer number.

        Returns:
            int: integer that equals the val argument when converted into hexadecimal.
        """
        decAsHex: int = 0
        # get each digit and reverse order
        decimal: list[int] = [ int(x) for x in [*str(val)] ]
        decimal.reverse()
        # calculate hex: dn-1 … d1 d0 (hex) = dn-1 * 16^n-1 + … + d1 * 16^1 + d0 * 16^0 (decimal)
        for i,digit in enumerate(decimal) :
            decAsHexDigit = digit * 16**i
            decAsHex += decAsHexDigit
        return(decAsHex)


    @staticmethod
    def _DecodeDecimalAsHex(val: int) -> int : 
        """Interprets an integer that was converted to a hexadecimal representation of a \
        decimal value. In other words, this method reverses _CodeDecimalAsHex().

        Args:
            val (int): Unsigned integer that was converted to a hexadecimal representation of a \
                decimal value.

        Returns:
            int: Unsigned integer as a true decimal number. 
        """
        return(int(hex(val).replace('0x','')))


    @staticmethod
    def _Custom140SETTIME(payload: tuple[int]) -> tuple[int] : 
        """Custom function to translate the payload for command #140 SET TIME.

        Args:
            payload (tuple[int]): Default translated payload.

        Returns:
            tuple[int]: Tuple of times.
        """
        return tuple([Pod8229._DecodeDecimalAsHex(x) for x in payload]) 
    
    
    @staticmethod
    def _Validate_Day(day: str|int) -> int : 
        """Raises an exception if the day is incorrectly formatted. If the day is given as \
        a string, it will be converted to its integer code. 

        Args:
            day (str | int): String day of the week or its repsective integer code. 

        Raises:
            Exception: The day integer argument must be 0-6.
            Exception: The day argument must be a str or int.

        Returns:
            int: Integer code representing a day of the week.
        """
        if(isinstance(day,str)) : 
            dayCode = Pod8229.CodeDayOfWeek(day)
        elif(isinstance(day,int)) : 
            if(day < 0 or day > 6) : 
                raise Exception('[!] The day integer argument must be 0-6.')
            dayCode = day
        else: 
            raise Exception('[!] The day argument must be a str or int.')
        return(dayCode)
        

    @staticmethod
    def _Validate_Hours(hours: list|tuple[bool|int]) -> list[bool|int] :
        """Raises an exception if the hours is incorrectly formatted. Converts the hours \
        into a list before returning it.

        Args:
            hours (list | tuple[bool | int]): Array with 24 items with values of 1/0 \
                representing each hour

        Raises:
            Exception: The hours argument must be a list or tuple.
            Exception: The hours argument must have exactly 24 items.
            Exception: The hours items must be 0 or 1.

        Returns:
            list[bool|int]: List with 24 items for each hour. The values are 1/0.
        """
        if( not isinstance(hours, list) and not isinstance(hours, tuple) ) : 
            raise Exception('[!] The hours argument must be a list or tuple.')
        if(len(hours) != 24 ) : 
            raise Exception('[!] The hours argument must have exactly 24 items.')
        for h in hours  :
            if(int(h) != 0 and int(h) != 1 ) : 
                raise Exception('[!] The hours items must be 0 or 1.')
        return(list(hours))
            

    @staticmethod
    def _Validate_Speed(speed: int|list|tuple[int]) -> list[int] :
        """Raises an exception if the speed is incorrectly formatted. If an integer speed \
        is given, it will convert it to a list. 

        Args:
            speed (int | list | tuple[int]): Motor speed (0-100). This can either be an \
                integer or a tuple/list of 24 speeds. 

        Raises:
            Exception: The speed argument must be an int, list, or tuple.
            Exception: The speed must be between 0 and 100.
            Exception: The speed argument must have exactly 24 items as a list/tuple.
            Exception: The speed must be between 0 and 100 for every list/tuple item.

        Returns:
            list[int]: List containing 24 motor speeds.
        """
        if( not isinstance(speed, list) and not isinstance(speed, tuple) and not isinstance(speed, int)) : 
            raise Exception('[!] The speed argument must be an int, list, or tuple.')
        if(isinstance(speed,int)) : 
            if( speed < 0 or speed > 100 ) : 
                raise Exception('[!] The speed must be between 0 and 100.')
            speedArr = [speed] * 24 
        else : 
            if(len(speed) != 24 ) : 
                raise Exception('[!] The speed argument must have exactly 24 items as a list/tuple.')
            for s in speed : 
                if( s < 0 or s > 100 ) : 
                    raise Exception('[!] The speed must be between 0 and 100 for every list/tuple item.')
            speedArr = speed
        return(list(speedArr))


    @staticmethod
    def _Validate_Schedule(schedule: bytes, size: int) -> bytes:
        """Raises an exception if the schedule is incorrectly formatted 

        Args:
            schedule (bytes): Bytes string containing the day schedule.
            size (int): Number of U8 bytes.

        Raises:
            Exception: The schedule must be bytes.
            Exception: The schedule is the incorrect size 

        Returns:
            bytes: Same as the schedule argument.
        """
        if(not isinstance(schedule, bytes)) : 
            raise Exception('[!] The schedule must be bytes.')
        if( len(schedule) != size * Pod.GetU(8) ) : 
            raise Exception('[!] The schedule must have U8x'+str(size)+'.')
        return(schedule)

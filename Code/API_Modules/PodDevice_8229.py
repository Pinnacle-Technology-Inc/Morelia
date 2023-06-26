# local imports 
from BasicPodProtocol   import POD_Basics
from PodCommands        import POD_Commands
from PodPacketHandling  import POD_Packets

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class POD_8229(POD_Basics) : 


    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self, port: str|int, baudrate:int=19200) -> None :
        # initialize POD_Basics
        super().__init__(port, baudrate=baudrate) 
        # get constants for adding commands 
        U8  = POD_Commands.U8()
        U16 = POD_Commands.U16()
        NOVALUE = POD_Commands.NoValue()
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
        self._commands.AddCommand(136, 'SET MOTOR SPEED',       (U16,),                 (U16,),                 False, 'Sets motor speed as a percentage, 0-100.  Replies with value set.')
        self._commands.AddCommand(137, 'GET MOTOR SPEED',       (0,),                   (U16,),                 False, 'Gets the motor speed as a percentage, 0-100.')
        self._commands.AddCommand(140, 'SET TIME',              (U8,U8,U8,U8,U8,U8,U8), (U8,U8,U8,U8,U8,U8,U8), False, 'Sets the RTC time.  Format is (Seconds, Minutes, Hours, Day, Month, Year (without century, so 23 for 2023), Weekday).  Weekday is 0-6, with Sunday being 0.  Binary Coded Decimal. Returns current time.  Note that the the seconds (and sometimes minutes field) can rollover during execution of this command and may not match what you sent.')
        self._commands.AddCommand(141, 'SET DAY SCHEDULE',      (U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8), # ( U8, U8 x 24 )
                                                                                        (0,),                   False, 'Sets the schedule for the day.  U8 day, followed by 24 hourly schedule values.  MSb in each byte is a flag for motor on (1) or off (0), and the remaining 7 bits are the speed (0-100).')
        self._commands.AddCommand(142, 'GET DAY SCHEDULE',      (U8,),                  (U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8), # ( U8 x 24 )
                                                                                                                False, 'Gets the schedule for the selected week day (0-6 with 0 being Sunday).')
        self._commands.AddCommand(143, 'REVERSE TIME EVENT',    (0,),                   (U16,),                 False, 'Indicates the bar has just reveresed.  Returns the time in seconds until the next bar reversal.')
        self._commands.AddCommand(144, 'SET REVERSE PARAMS',    (U16,U16),              (0,),                   False, 'Sets (Base Time, Variable Time) for random reverse in seconds.  The random reverse time will be base time + a random value in Variable Time range.')
        self._commands.AddCommand(145, 'GET REVERSE PARAMS',    (0,),                   (U16,U16),              False, 'Gets the base and variable times for random reverse, in seconds.')
        self._commands.AddCommand(146, 'SET MOTOR STATE',       (U16,),                 (U16,),                 False, 'Sets whether the motor is on or off.  1 for On, 0 for Off.')
        self._commands.AddCommand(147, 'GET MOTOR STATE',       (0,),                   (U16,),                 False, 'Gets the motor state.')
        self._commands.AddCommand(148, 'LCD RESET',             (U8,),                  (0,),                   False, 'Resets the LCD.  Probably never need to send this.  Can cause desync between LCD state and system state.')
        self._commands.AddCommand(149, 'SET ID',                (U16,),                 (0,),                   False, 'Sets the system ID displayed on the LCD.')
        self._commands.AddCommand(150, 'SET RANDOM REVERSE',    (U8,),                  (0,),                   False, 'Enables or Disables Random Reverse function.  0 = disabled, Non-Zero = enabled.')
        self._commands.AddCommand(151, 'GET RANDOM REVERSE',    (0,),                   (U8,),                  False, 'Reads the Random Reverse function.  0 = disabled, non-zero = enabled.')
        # recieved only commands below vvv 
        self._commands.AddCommand(200, 'LCD SET MOTOR STATE',   (NOVALUE,),             (U16,),                 False, 'Indicates that the motor state has been changed by the LCD.  1 for On, 0 for Off.')
        self._commands.AddCommand(201, 'LCD SET MOTOR SPEED',   (NOVALUE,),             (U16,),                 False, 'Indicates the motor speed has been changed by the LCD.  0-100 as a percentage.')
        self._commands.AddCommand(202, 'LCD SET DAY SCHEDULE',  (NOVALUE,),             (U8,U8,U8,U8),          False, 'Indicates the LCD has changed the day schedule.  Byte 3 is weekday, Byte 2 is hours 0-7, Byte 3 is hours 8-15, and byte is hours 16-23.  Each bit represents the motor state in that hour, 1 for on and 0 for off.  Speed is whatever the current motor speed is.')
        self._commands.AddCommand(204, 'LCD SET MODE',          (NOVALUE,),             (U16,),                 False, 'Indicates the mode has been changed by the display.  0 = Manual, 1 = PC Control, 2 = Internal Schedule.')


    # ============ PUBLIC METHODS ============      ========================================================================================================================


    @staticmethod
    def BuildSetDayScheduleArgument(day: str|int, schedule: list[int]) -> tuple[int] : 
        # use this for getting the command #141 'SET DAY SCHEDULE' argument 
        # get good value
        validDay = POD_8229._Validate_Day(day)
        # prepend the day to the schedule  
        return( tuple( schedule.insert(0, validDay) ) )


    @staticmethod
    def CodeDaySchedule(hours: list|tuple[bool|int], speed: int|list|tuple[int]) -> list[int] : 
        # use this for getting the command #141 'SET DAY SCHEDULE' U8x24 argument component 
        # get good values 
        validHours = POD_8229._Validate_Hours(hours)
        validSpeed = POD_8229._Validate_Speed(speed) 
        # modify bits of each hour 
        schedule = [0] * 24
        for i in range(24) : 
            # msb in each byte is a flag for motor on (1) or off (0), and the remaining 7 bits are the speed (0-100)
            schedule[i] = ( validHours[i] << 7 ) | validSpeed[i]
        # return tuple that works as an argument for command #141 'SET DAY SCHEDULE'
        return( list(schedule) )


    @staticmethod
    def DecodeDaySchedule(schedule: bytes) -> dict[str,int|list[int]] :
        # use this for getting the command #141 'SET DAY SCHEDULE' argument 
        # check for valid arguments 
        validSchedule = POD_8229._Validate_Schedule(schedule, 24)
        # decode each hour
        hours  = [None] * 24
        speeds = [None] * 24
        for i in range(24) : 
            thisHr = validSchedule[2*i:2*i+2]
            hours[i]  = POD_Packets.ASCIIbytesToInt_Split(thisHr, 8, 7) # msb in each byte is a flag for motor on (1) or off (0)
            speeds[i] = POD_Packets.ASCIIbytesToInt_Split(thisHr, 7, 0) # remaining 7 bits are the speed (0-100)
        # check if all speeds are the same 
        if(len(set(speeds)) == 1) : 
            # speeds has all identical elements
            speeds = speeds[0]
        # return hour and speeds 
        return({ 
            'Hour'  : hours, 
            'Speed' : speeds
        })
    

    @staticmethod
    def DecodeLCDSchedule(schedule: bytes) -> dict[str,int|list[int]] : 
        # use this for translating the command #202	'LCD SET DAY SCHEDULE' return 
        # check for valid arguments 
        validSchedule = POD_8229._Validate_Schedule(schedule, 4)
        # Byte 3 is weekday, Byte 2 is hours 0-7, Byte 1 is hours 8-15, and byte 0 is hours 16-23. 
        day = POD_8229.DecodeDayOfWeek( POD_Packets.AsciiBytesToInt( validSchedule[0:2] ) )
        hourBytes = validSchedule[2:]
        # Get each hour bit 
        hours = []
        topBit = POD_Commands.U8() * 3 * 4 # (number of hex characters per U8) * (number of U8 bytes) * (bits per hex character)
        while(topBit > 0 ) : 
            hours.append( POD_Packets.ASCIIbytesToInt_Split( hourBytes, topBit, topBit-1))
            topBit -= 1
        # return decoded LCD SET DAY SCHEDULE value
        return({
            'Day' : day,
            'Hours' : hours # Each bit represents the motor state in that hour, 1 for on and 0 for off.
        })


    @staticmethod
    def CodeDayOfWeek(day : str) -> int :
        # Weekday is 0-6, with Sunday being 0
        match str(day).lower()[:2] : 
            case 'su' : return(0) # sunday
            case 'tu' : return(2) # tuesday
            case 'th' : return(4) # thursday
            case 'sa' : return(6) # saturday
        match str(day).lower()[:1] : 
            case 'm'  : return(1) # monday
            case 'w'  : return(3) # wednesday 
            case 'f'  : return(5) # friday 
        raise Exception('[!] Invalid day of the week: '+str(day))  
    

    @staticmethod
    def DecodeDayOfWeek(day: int) -> str :
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
            

    def TranslatePODpacket(self, msg: bytes) -> dict[str,int|dict[str,int]] : 
        # get command number (same for standard and binary packets)
        cmd = POD_Packets.AsciiBytesToInt(msg[1:5])
        # these commands have some specific formatting 
        specialCommands = [142, 202] # 142 GET DAY SCHEDULE # 202 LCD SET DAY SCHEDULE
        if(cmd in specialCommands):
            msgDict = POD_Basics.UnpackPODpacket_Standard(msg)
            transdict = { 'Command Number' : POD_Packets.AsciiBytesToInt( msgDict['Command Number'] ) } 
            if(cmd == 142): # 142 GET DAY SCHEDULE
                transdict['Payload'] = self.DecodeDaySchedule(msgDict['Payload'])
            else : # 202 LCD SET DAY SCHEDULE
                transdict['Payload'] = self.DecodeLCDSchedule(msgDict['Payload'])
        # standard packet 
        else: 
            return(self.TranslatePODpacket_Standard(msg)) # TranslatePODpacket_Standard does not handle TTL well, hence elif statements 



    # ============ PROTECTED METHODS ============      ========================================================================================================================    
    
    
    @staticmethod
    def _Validate_Day(day: str|int) -> int : 
        if(isinstance(day,str)) : 
            dayCode = POD_8229.CodeDayOfWeek(day)
        elif(isinstance(day,int)) : 
            if(day < 0 or day > 6) : 
                raise Exception('[!] The day integer argument must be 0-6.')
            dayCode = day
        else: 
            raise Exception('[!] The day argument must be a str or int.')
        return(dayCode)
        

    @staticmethod
    def _Validate_Hours(hours: list|tuple[bool|int]) -> list[bool|int] :
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
        if(not isinstance(schedule, bytes)) : 
            raise Exception('[!] The schedule must be bytes.')
        if( len(schedule) != size * POD_Commands.U8() ) : 
            raise Exception('[!] The schedule must have U8x24.')
        return(schedule)
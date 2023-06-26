# local imports 
from BasicPodProtocol   import POD_Basics
from PodCommands        import POD_Commands

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
        self._commands.AddCommand(141, 'SET DAY SCHEDULE',      (U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8), 
                                                                                        (0,),                   False, 'Sets the schedule for the day.  U8 day, followed by 24 hourly schedule values.  MSb in each byte is a flag for motor on (1) or off (0), and the remaining 7 bits are the speed (0-100).')
        self._commands.AddCommand(142, 'GET DAY SCHEDULE',      (U8,),                  (U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8,U8), 
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
        self._commands.AddCommand(200, 'LCD SET MOTOR STATE',   (NOVALUE,),             (U16,),                 False, 'Indicates that the motor state has been changed by the LCD.  1 for On, 0 for Off.')
        self._commands.AddCommand(201, 'LCD SET MOTOR SPEED',   (NOVALUE,),             (U16,),                 False, 'Indicates the motor speed has been changed by the LCD.  0-100 as a percentage.')
        self._commands.AddCommand(202, 'LCD SET DAY SCHEDULE',  (NOVALUE,),             (U8,U8,U8,U8),          False, 'Indicates the LCD has changed the day schedule.  Byte 3 is weekday, Byte 2 is hours 0-7, Byte 3 is hours 8-15, and byte is hours 16-23.  Each bit represents the motor state in that hour, 1 for on and 0 for off.  Speed is whatever the current motor speed is.')
        self._commands.AddCommand(204, 'LCD SET MODE',          (NOVALUE,),             (U16,),                 False, 'Indicates the mode has been changed by the display.  0 = Manual, 1 = PC Control, 2 = Internal Schedule.')

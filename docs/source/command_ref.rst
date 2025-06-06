####################################
POD Device Command Reference 📚
####################################

This page is meant to serve as a reference for all
commands that can be sent to POD devices supported
by Morelia using the :doc:`low-level API </low_level>`. 
**If you haven't read that page, read it first.**

===================
Data Types 101 🥗
===================
Every POD device enforces `data types <https://en.wikipedia.org/wiki/Data_type>`_ for the values sent to/recieved
from it. For the uninitiated, these are basically the valid values you are allowed to pass to a specific command. POD devices
use three fundamental data types:

======================= =================== ==============
Type Name               Shorthand Notation  Valid Values
======================= =================== ==============
Unsigned 8-Bit Integer  U8                  [0-255]
Unsigned 16-Bit Integer U16                 [0-65535]
Unsigned 32-Bit Integer U32                 [0-4294967295]
======================= =================== ==============

===================
Device Commands 🔌
===================

---------------
Common Commands
---------------
These commands are common across all POD devices.

.. list-table::
   :header-rows: 1
   :widths: auto

   * - Command Number
     - Command Name
     - Arguments
     - Returns
     - Description

   * - 0
     - ACK
     - None
     - None
     - Basic ACK command. Unused, because in normal communications the sent command is echoed instead.

   * - 1
     - NACK
     - None
     - None
     - Response to an unknown command number.

   * - 2
     - PING
     - None
     - None
     - Used to verify device is present and communicating.

   * - 3
     - RESET
     - None
     - None
     - Indicates a device reset occurred. Also sent at startup.

   * - 7
     - BOOT
     - None
     - None
     - Instructs the device to enter bootload mode. After issuing this command, the bootload process must be completed or the device must be manually reset.

   * - 8
     - TYPE
     - None
     - U8
     - Returns the device type value. This is a unique value for each device. (e.g. is 0x30 for 8206HR).

   * - 12
     - FIRMWARE VERSION
     - None
     - U8, U8, U16
     - Returns the device firmware version as 3 ASCII-encoded hex values. This is, the return values are meant to be intreprated as ASCII, which gives the version number in hexadecimal. Additonally, the U16 encodes two seperate ASCII characters, encoded by the leftmost and rightmost bytes respectively. So 1.0.10 would come back as 0x31, 0x30, 0x00, 0x41 (ASCII for 1.0.A).


------------------------
8206HR-Specific Commands 
------------------------
.. list-table::
   :header-rows: 1
   :widths: auto

   * - Command Number
     - Command Name
     - Arguments
     - Returns
     - Description

   * - 4
     - ERROR
     - None
     - U8
     - Indicates an error has occurred, of the returned type. Not actually used.

   * - 6
     - STREAM
     - U8
     - U8
     - Command to change streaming state. 0 = OFF, 1 = ON. Reply returns the argument sent. May reply *after* streaming starts.

   * - 100
     - GET SAMPLE RATE
     - None
     - U16
     - Gets the current sample rate of the system, in Hz.

   * - 101
     - SET SAMPLE RATE
     - U16
     - None
     - Sets the sample rate of the system, in Hz. Valid values are 100 - 2000 currently (could be up to 4000 in the future).

   * - 102
     - GET LOWPASS
     - U8
     - U16
     - Gets the lowpass filter for the desired channel (0 = EEG1, 1 = EEG2, 2 = EEG3/EMG). Returns the value in Hz.

   * - 103
     - SET LOWPASS
     - U8, U16
     - None
     - Sets the lowpass filter for the desired channel (0 = EEG1, 1 = EEG2, 2 = EEG3/EMG) to the desired value (11 - 500) in Hz.

   * - 104
     - SET TTL OUT
     - U8, U8
     - None
     - Sets the selected TTL pin (0,1,2,3) to an output and sets the value (0-1).

   * - 105
     - GET TTL IN
     - U8
     - U8
     - Sets the selected TTL pin (0,1,2,3) to an input and returns the value (0-1).

   * - 106
     - GET TTL PORT
     - None
     - U8
     - Gets the value of the entire TTL port as a byte. Does not modify pin direction.

   * - 107
     - GET FILTER CONFIG
     - None
     - U8
     - Gets the hardware filter configuration. 0=SL, 1=SE (Both 40/40/100Hz lowpass), 2 = SE3 (40/40/40Hz lowpass).

It is also worth noting that packets containing streaming data will
have the command number 180.

------------------------
8401HR-Specific Commands 
------------------------
.. list-table::
   :header-rows: 1
   :widths: auto

   * - Command Number
     - Command Name
     - Arguments
     - Returns
     - Description

   * - 4
     - ERROR
     - None
     - U8
     - Indicates an error has occurred, of the returned type. Not actually used.

   * - 6
     - STREAM
     - U8
     - U8
     - Command to change streaming state. 0 = OFF, 1 = ON. Reply returns the argument sent. May reply *after* streaming starts.

   * - 100
     - GET SAMPLE RATE
     - None
     - U16
     - Gets the current sample rate of the system, in Hz.

   * - 101
     - SET SAMPLE RATE
     - U16
     - None
     - Sets the sample rate of the system, in Hz. Valid values are 2000 - 20000 currently.

   * - 102
     - GET HIGHPASS
     - U8
     - U8
     - Reads the highpass filter value for a channel. Requires the channel to read. Returns 0-3, where 0 = 0.5Hz, 1 = 1Hz, 2 = 10Hz, 3 = DC / No Highpass.

   * - 103
     - SET HIGHPASS
     - U8, U8
     - None
     - Sets the highpass filter for a channel. Requires channel to set and filter value. Values are the same as returned in GET HIGHPASS.

   * - 104
     - GET LOWPASS
     - U8
     - U16
     - Gets the lowpass filter for the desired channel. Requires the channel to read. Returns the value in Hz.

   * - 105
     - SET LOWPASS
     - U8, U16
     - None
     - Sets the lowpass filter for the desired channel to the desired value (21 - 15000) in Hz. Requires the channel and value in Hz.

   * - 106
     - GET DC MODE
     - U8
     - U8
     - Gets the DC mode for the channel. Requires the channel to read. Returns 0 = Subtract VBias, 1 = Subtract AGND. Typically 0 for biosensors and 1 for EEG/EMG.

   * - 107
     - SET DC MODE
     - U8, U8
     - None
     - Sets the DC mode for the selected channel. Requires the channel and value to set. Values are the same as in GET DC MODE.

   * - 112
     - GET BIAS
     - U8
     - U16
     - Gets the bias on a given channel. Returns the DAC value as a 16-bit 2's complement value, representing a value from ±2.048V.

   * - 113
     - SET BIAS
     - U8, U16
     - None
     - Sets the bias on a given channel. Requires the channel and DAC value as specified in GET BIAS. Note that for most preamps, only channel 0/A DAC values are used. This can cause issues with bias subtraction on preamps with multiple bio channels.

   * - 114
     - GET EXT0 VALUE
     - None
     - U16
     - Reads the analog value on the EXT0 pin. Returns an unsigned 12-bit value, representing a 3.3V input. Normally used to identify preamps. Note that this function takes some time and blocks, so it should not be called during data acquisition if possible.

   * - 115
     - GET EXT1 VALUE
     - None
     - U16
     - Reads the analog value on the EXT1 pin. Returns an unsigned 12-bit value, representing a 3.3V input. Normally used to identify if an 8480 is present. Similar caveat regarding blocking as GET EXT0 VALUE.

   * - 116
     - SET EXT0
     - U8
     - None
     - Sets the digital value of EXT0, 0 or 1.

   * - 117
     - SET EXT1
     - U8
     - None
     - Sets the digital value of EXT1, 0 or 1.

   * - 121
     - SET INPUT GROUND
     - U8
     - None
     - Sets whether channel inputs are grounded or connected to the preamp. Bitfield: bits 0-3. High nibble should be 0s. 0 = Grounded, 1 = Connected to Preamp.

   * - 122
     - GET INPUT GROUND
     - None
     - U8
     - Returns the bitmask value from SET INPUT GROUND.

   * - 127
     - SET TTL CONFIG
     - U8, U8
     - None
     - Configures the TTL pins. First argument is output setup: 0 is open collector, 1 is push-pull. Second argument is input setup: 0 is analog, 1 is digital. Bit 7 = EXT0, bit 6 = EXT1, bits 4–5 unused, bits 0–3 = TTL pins.

   * - 128
     - GET TTL CONFIG
     - None
     - U8, U8
     - Gets the TTL config byte. Values are as per SET TTL CONFIG.

   * - 129
     - SET TTL OUTS
     - U8, U8
     - None
     - Sets the TTL pins. First byte is a bitmask: 0 = do not modify, 1 = modify. Second byte is bit field: 0 = low, 1 = high.

   * - 130
     - GET SS CONFIG
     - U8
     - U8
     - Gets the second stage gain config. Requires the channel. Returns a bitfield: Bit 0 = 0 for 0.5Hz Highpass, 1 for DC Highpass. Bit 1 = 0 for 5x gain, 1 for 1x gain.

   * - 131
     - SET SS CONFIG
     - U8, U8
     - None
     - Sets the second stage gain config. Requires the channel and a config bitfield as per GET SS CONFIG.

   * - 132
     - SET MUX MODE
     - U8
     - None
     - Sets mux mode on or off. This causes EXT1 to toggle periodically to control 2BIO/3EEG preamps. 0 = Off, 1 = On.

   * - 133
     - GET MUX MODE
     - None
     - U8
     - Gets the state of mux mode. See SET MUX MODE.

   * - 134
     - GET TTL ANALOG
     - U8
     - U16
     - Reads a TTL input as an analog signal. Requires a channel to read. Returns a 10-bit analog value. Same caveats and restrictions as GET EXT* VALUE commands. Normally you would just enable an extra channel in Sirenia for this.

It is also worth noting that packets containing streaming data will
have the command number 181.

------------------------
8229-Specific Commands 
------------------------
.. list-table::
   :header-rows: 1
   :widths: auto

   * - Command Number
     - Command Name
     - Arguments
     - Returns
     - Description

   * - 128
     - SET MOTOR DIRECTION
     - U16
     - U16
     - Sets motor direction, 0 for clockwise and 1 for counterclockwise. Returns value set.

   * - 129
     - GET MOTOR DIRECTION
     - None
     - U16
     - Returns motor direction value.

   * - 132
     - SET MODE
     - U8
     - U8
     - Sets the current system mode. 0 = Manual, 1 = PC Control, 2 = Internal Schedule. Returns the current mode.

   * - 133
     - GET MODE
     - None
     - U8
     - Gets the current system mode.

   * - 136
     - SET MOTOR SPEED
     - U16
     - U16
     - Sets motor speed as a percentage, 0–100. Replies with value set.

   * - 137
     - GET MOTOR SPEED
     - None
     - U16
     - Gets the motor speed as a percentage, 0–100.

   * - 140
     - SET TIME
     - U8 x 7
     - U8 x 7
     - Sets the RTC time. Format is (Seconds, Minutes, Hours, Day, Month, Year [without century, so 23 for 2023], Weekday). Weekday is 0–6, with Sunday being 0. Binary Coded Decimal. Returns current time. Note that the seconds (and sometimes minutes field) can roll over during execution of this command and may not match what you sent.

   * - 141
     - SET DAY SCHEDULE
     - U8, U8 x 24
     - None
     - Sets the schedule for the day. U8 day, followed by 24 hourly schedule values. MSB in each byte is a flag for motor on (1) or off (0), and the remaining 7 bits are the speed (0–100).

   * - 142
     - GET DAY SCHEDULE
     - U8
     - U8 x 24
     - Gets the schedule for the selected weekday (0–6 with 0 being Sunday).

   * - 144
     - SET REVERSE PARAMS
     - U16, U16
     - None
     - Sets (Base Time, Variable Time) for random reverse in seconds. The random reverse time will be base time + a random value in the Variable Time range.

   * - 145
     - GET REVERSE PARAMS
     - None
     - U16, U16
     - Gets the base and variable times for random reverse, in seconds.

   * - 146
     - SET MOTOR STATE
     - U16
     - U16
     - Sets whether the motor is on or off. 1 for On, 0 for Off. Returns the previous motor state.

   * - 147
     - GET MOTOR STATE
     - None
     - U16
     - Gets the motor state.

   * - 148
     - LCD RESET
     - U8
     - None
     - Resets the LCD. Probably never needs to be sent. Can cause desync between LCD state and system state.

   * - 149
     - SET ID
     - U16
     - None
     - Sets the system ID displayed on the LCD.

   * - 150
     - SET RANDOM REVERSE
     - U8
     - None
     - Enables or disables Random Reverse function. 0 = disabled, non-zero = enabled.

   * - 151
     - GET RANDOM REVERSE
     - None
     - U8
     - Reads the Random Reverse function. 0 = disabled, non-zero = enabled.

For the 8229, there are some control packets that are only ever sent *from* the
device (i.e. you should never send these). They are as follows

.. list-table:: Recievable-only control packets for the 8229.
   :header-rows: 1
   :widths: auto

   * - Command Number
     - Command Name
     - Returns
     - Description

   * - 143
     - REVERSE TIME EVENT
     - U16
     - Indicates the bar has just reversed. Returns the time in seconds until the next bar reversal.


   * - 200
     - LCD SET MOTOR STATE
     - U16
     - Indicates that the motor state has been changed by the LCD. 1 for On, 0 for Off.

   * - 201
     - LCD SET MOTOR SPEED
     - U16
     - Indicates the motor speed has been changed by the LCD. 0–100 as a percentage. Returns previous motor speed.

   * - 202
     - LCD SET DAY SCHEDULE
     - U8 x 4
     - Indicates the LCD has changed the day schedule. Byte 3 is weekday, Byte 2 is hours 0–7, Byte 1 is hours 8–15, and Byte 0 is hours 16–23. Each bit represents the motor state in that hour, 1 for on and 0 for off. Speed is whatever the current motor speed is.

   * - 204
     - LCD SET MODE
     - U16
     - Indicates the mode has been changed by the display. 0 = Manual, 1 = PC Control, 2 = Internal Schedule.

------------------------
8480-Specific Commands 
------------------------
.. list-table::
   :header-rows: 1
   :widths: auto

   * - Command Number
     - Command Name
     - Arguments
     - Returns
     - Description

   * - 4
     - ERROR
     - None
     - U8
     - Indicates an error has occurred, of the returned type. Not actually used.

   * - 100
     - RUN STIMULUS
     - U8
     - None
     - Requires U8 channel. Runs the stimulus on the selected channel (0 or 1). Will generally be immediately followed by a 133 EVENT STIM START packet, and followed by a 134 EVENT STIM END packet after the stimulus completes.

   * - 101
     - GET STIMULUS
     - U8
     - U8, U16 x 4, U32, U8
     - Requires U8 channel. Gets the current stimulus configuration for the selected channel.

   * - 102
     - SET STIMULUS
     - U8, U16 x 4, U32, U8
     - None
     - Sets the stimulus configuration on the selected channel.

   * - 108
     - GET TTL SETUP
     - U8
     - U8, U8
     - Requires U8 channel. Returns U8 config flags, and U8 debounce value in ms. See :doc:`8480 documentation </stimulus>` for config flags format.

   * - 109
     - SET TTL SETUP
     - U8, U8, U8
     - None
     - Sets the TTL setup for the channel. Format is Channel, Config Flags, Debounce in ms. See :doc:`8480 documentation </stimulus>` for config flags format.

   * - 110
     - GET TTL PULLUPS
     - None
     - U8
     - Gets whether TTL pullups are enabled on the TTL lines. 0 = no pullups, non-zero = pullups enabled.

   * - 111
     - SET TTL PULLUPS
     - U8
     - NA
     - Sets whether pullups are enabled on the TTL lines. 0 = pullups disabled, non-zero = pullups enabled.

   * - 116
     - GET LED CURRENT
     - None
     - U16, U16
     - Gets the setting for LED current for both channels in mA. CH0 CH1.

   * - 117
     - SET LED CURRENT
     - U8, U16
     - None
     - Requires U8 channel. Sets the selected channel LED current to the given value in mA, from 0–600.

   * - 118
     - GET ESTIM CURRENT
     - None
     - U16, U16
     - Gets the setting for the ESTIM current for both channels, in percentage. CH0 then CH1.

   * - 119
     - SET ESTIM CURRENT
     - U8, U16
     - None
     - Requires U8 channel. Sets the selected channel ESTIM current to the given value in percentage, from 0–100.

   * - 124
     - GET PREAMP TYPE
     - None
     - U16
     - Gets the stored preamp value.

   * - 125
     - SET PREAMP TYPE
     - U16
     - None
     - Sets the preamp value, from 0–1023. This should match the table in Sirenia. It's a 10-bit code that tells the 8401 what preamp is connected. Only needed when used with an 8401.

   * - 126
     - GET SYNC CONFIG
     - None
     - U8
     - Gets the sync config byte. See format in :doc:`8480 documentation </stimulus>`.

   * - 127
     - SET SYNC CONFIG
     - U8
     - None
     - Sets the sync config byte. See format in :doc:`8480 documentation </stimulus>`.

For the 8480, there are some control packets that are only ever sent *from* the
device (i.e. you should never send these). They are as follows

.. list-table:: Recievable-only control packets for the 8480.
   :header-rows: 1
   :widths: auto

   * - Command Number
     - Command Name
     - Returns
     - Description

   * - 132
     - EVENT TTL
     - U8
     - Indicates a TTL event has occurred on the indicated U8 TTL input. If debounce is non-zero, then this will not occur until the debounce has completed successfully.

   * - 133
     - EVENT STIM START
     - U8
     - Indicates the start of a stimulus. Returns U8 channel.

   * - 134
     - EVENT STIM STOP
     - U8
     - Indicates the end of a stimulus. Returns U8 channel.

   * - 135
     - EVENT LOW CURRENT
     - U8
     - Indicates a low current status on one or more of the LED channels. U8 bitmask indicates which channels have low current. Bit 0 = Ch0, Bit 1 = Ch1.

The ``SET STIMULUS`` and ``GET STIMULUS`` command arguments/return values are more complex than others.
In order to make sense of the arguments/response, see the following table.

.. list-table:: SET/GET STIMULUS command format.
   :header-rows: 1
   :widths: auto

   * - Index
     - Type
     - Name
     - Description

   * - 0
     - U8
     - Channel
     - The channel for the stimulus, either 0 or 1.

   * - 2
     - U16
     - Stimulus Period, ms portion
     - The period (time between pulses) of the stimulus event in ms. Added with the us portion gives the total period.

   * - 3
     - U16
     - Stimulus Period, us portion
     - The sub-ms portion of the period. Added with the ms portion gives the total period.

   * - 4
     - U16
     - Stimulus Width, ms portion
     - The width of each stimulus pulse, in ms. Added with the us portion gives the total width. Note that if biphasic stimulation is configured for this channel, the total width cannot be greater than half the period.

   * - 5
     - U16
     - Stimulus Width, us portion
     - The sub-ms portion of the pulse width. Added with the ms portion gives the total period. Biphasic restriction applies to total of ms + us portions.

   * - 6
     - U32
     - Stimulus Repeat Count
     - The number of stimulus pulses to perform.

   * - 7
     - U8
     - Config Flags
     - Config Flags byte. See :doc:`8480 documentation </stimulus>` for format.


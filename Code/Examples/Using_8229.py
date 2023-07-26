# add directory path to code 
import sys, os
aroundApi = os.path.abspath('.').split('Python-POD-API')
apiPath = aroundApi[0] + 'Python-POD-API'
if(len(aroundApi) > 1 and (not aroundApi[1].startswith('\\'))): apiPath += aroundApi[1].split('\\')[0]
sys.path.insert(0, os.path.join( apiPath, 'Code', 'API_Modules') )

# enviornment imports
import time

# local imports
from SerialCommunication    import COM_io
from PodDevice_8229         import POD_8229

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

# ===============================================================

def ChoosePort() -> str : 
    # get ports
    portList = COM_io.GetCOMportsList()
    print('Available COM Ports: '+', '.join(portList))
    # request port from user
    choice = input('Select port: COM')
    # search for port in list
    for port in portList:
        if port.startswith('COM'+choice):
            return(port)
    print('[!] COM'+choice+' does not exist. Try again.')
    return(ChoosePort())

def Write(pod: POD_8229, cmd: str | int, payload: int | bytes | tuple[int | bytes] = None) : 
    write = pod.WritePacket(cmd, payload)
    write = pod.TranslatePODpacket(write)
    print('Write:\t', write)

def Read(pod: POD_8229) : 
    read = pod.ReadPODpacket(timeout_sec=1)
    read = pod.TranslatePODpacket(read)
    print('Read:\t', read)

def RunCommand(pod: POD_8229, cmd: str | int, payload: int | bytes | tuple[int | bytes] = None) :
   Write(pod,cmd,payload)
   Read(pod)

# ===============================================================

# create instance of 8206-HR POD device

port: str = ChoosePort()
pod = POD_8229(port)

# write each command:

print('~~ BASICS ~~')
RunCommand(pod, 'PING') # Used to verify device is present and communicating
RunCommand(pod, 'TYPE') # Returns the device type value.  This is a unique value for each device.
RunCommand(pod, 'FIRMWARE VERSION') # Returns the device firmware version as 3 values.  So 1.0.10 would come back as 0x31, 0x30, 0x00, 0x41

print('~~ TIME ~~')
timeNow: tuple[int] = pod.GetCurrentTime()
RunCommand(pod, 'SET TIME', timeNow) # Sets the RTC time.  Format is (Seconds, Minutes, Hours, Day, Month, Year (without century, so 23 for 2023), Weekday).  Weekday is 0-6, with Sunday being 0.  Binary Coded Decimal. Returns current time.  Note that the the seconds (and sometimes minutes field) can rollover during execution of this command and may not match what you sent. 

print('~~ ID ~~')
sysId: int = 42
RunCommand(pod, 'SET ID', sysId) # Sets the system ID displayed on the LCD

print('~~ MODE ~~')
mode: int = 0
RunCommand(pod, 'SET MODE', mode) # Sets the current system mode - 0 = Manual, 1 = PC Control, 2 = Internal Schedule.  Returns the current mode.
RunCommand(pod, 'GET MODE') # Gets the current system mode

print('~~ MOTOR DIRECTION ~~')
motorDirect: int = 0
RunCommand(pod, 'SET MOTOR DIRECTION', motorDirect) # Sets motor direction, 0 for clockwise and 1 for counterclockwise.  Returns value set.
RunCommand(pod, 'GET MOTOR DIRECTION') # Returns motor direction value

print('~~ MOTOR SPEED ~~')
speed: int = 75 
RunCommand(pod, 'SET MOTOR SPEED', speed) # Sets motor speed as a percentage, 0-100.  Replies with value set.
RunCommand(pod, 'GET MOTOR SPEED') # Gets the motor speed as a percentage, 0-100

print('~~ MOTOR STATE ~~')
pod.WriteRead('SET RANDOM REVERSE', 0)
RunCommand(pod, 'SET MOTOR STATE', 1) # Sets whether the motor is on or off.  1 for On, 0 for Off. 
RunCommand(pod, 'GET MOTOR STATE') # Gets the motor state
onTime_sec = 5
time.sleep(onTime_sec)
RunCommand(pod, 'SET MOTOR STATE', 0) # Sets whether the motor is on or off.  1 for On, 0 for Off. 
RunCommand(pod, 'GET MOTOR STATE') # Gets the motor state

print('~~ REVERSE ~~')
randReverse: int = 1
RunCommand(pod, 'SET RANDOM REVERSE', randReverse) # Enables or Disables Random Reverse function.  0 = disabled, Non-Zero = enabled
RunCommand(pod, 'GET RANDOM REVERSE') # Reads the Random Reverse function.  0 = disabled, non-zero = enabled
baseTime_sec = 2
variableTime_sec = 3
RunCommand(pod, 'SET REVERSE PARAMS', (baseTime_sec,variableTime_sec)) # Sets (Base Time, Variable Time) for random reverse in seconds.  The random reverse time will be base time + a random value in Variable Time range
RunCommand(pod, 'GET REVERSE PARAMS') # Gets the base and variable times for random reverse, in seconds
testReverse_sec: int = 10
if(testReverse_sec > 0) : 
    pod.WriteRead('SET MOTOR STATE', 1)
    time.sleep(testReverse_sec)
    pod.WritePacket('SET MOTOR STATE', 0)
    # print all output
    streaming: bool = True
    while(streaming) : 
        try: 
            Read(pod)
        except: 
            streaming = False

print('~~ SCHEDULE ~~')
day: int = 0 
hours: tuple[bool] = (True, False, True, False, True, False, True, False, True, False, True, False, True, False, True, False, True, False, True, False, True, False, True, False)
schedule: tuple[int] = pod.BuildSetDayScheduleArgument(day,hours,speed)
RunCommand(pod, 'SET DAY SCHEDULE', schedule) # Sets the schedule for the day.  U8 day, followed by 24 hourly schedule values. 
RunCommand(pod, 'GET DAY SCHEDULE', 0) # Gets the schedule for the selected week day (0-6 with 0 being Sunday).
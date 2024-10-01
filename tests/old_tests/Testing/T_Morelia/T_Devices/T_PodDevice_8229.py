import random

from Testing.T_Morelia.TestProtocol import RunningTests, TestResult
from Morelia.Devices import Pod8229
from Morelia.packet import ControlPacket

# authorship
__author__      = "James Hurd"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert", "James Hurd"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"


class T_Pod8229 :

    def __init__(self, port: str|None = None, baudrate: int = 19200, forbidden: list[str] = []) -> None :
        
        if (port is None) :
            print('~~~~~~~~~~ 8229 ~~~~~~~~~~')
            self.port: str = Pod8229.ChoosePort(forbidden)
            print('~~~~~~~~~~~~~~~~~~~~~~~~~~~~')
        else:
            self.port: str = port

        self.pod: Pod8229 = Pod8229(self.port, baudrate)

        #replies with a packet that has no payload, so we throw away.
        self.pod.WriteRead('SET RANDOM REVERSE', 0)
        if (self.pod.WriteRead('GET RANDOM REVERSE').payload != (0,)) :
           raise RuntimeError('Unable to turn off random reverse mode, so test will be unreliable.')

        if self.pod.WriteRead('SET MODE', 0).payload != (0,) :
           raise RuntimeError('Unable to set mode to manual so test will be unreliable.')

        self.pod.WriteRead('SET MOTOR STATE', 0)
        if self.pod.WriteRead('GET MOTOR STATE').payload != (0,) :
           raise RuntimeError('Unable to turn off motor so test will be unreliable.')
        
        self._SetDefaultSchedule()

    def _SetDefaultSchedule(self) -> None:

       default_schedule: list[int] = Pod8229.CodeDaySchedule( *[ [0 for _ in range(24)] for _ in range(2) ] )

       for day in range(7):

           send_payload: tuple[int] = tuple([day] + default_schedule)
           self.pod.WriteRead('SET DAY SCHEDULE', send_payload)

           get_response: ControlPacket = self.pod.WriteRead('GET DAY SCHEDULE', day)
           
           get_response_payload: dict[str, tuple[int]] = get_response.payload

           if (get_response_payload['Hour'] != tuple([0 for _ in range(24)]) or get_response_payload['Speed'] != 0 ) :
                raise RuntimeError('Unable to set default schedule.') 

    def RunTests(self, printTests: bool = True) -> tuple[int,int]: 
        """Run all tests on Morelia.Packets.ControlPacket

        Args:
            printTests (bool, optional): Make True to print the test results and messages. Defaults to True.
        
        Returns:
            tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
        """

        tests = {
            "1. Ping:\t\t"          : self.Ping,
            "2. Type:\t\t"          : self.Type,
            "3. Firmware:\t\t"      : self.FirmVer,
            "4. Mode:\t\t"          : self.Mode,
            "5. Motor:\t\t"         : self.Motor,
            "6. Time:\t\t"          : self.Time,
            "7. Schedule:\t\t"      : self.Schedule,
        }

        return RunningTests.RunTests(tests, 'Pod8229', printTests=printTests)

    def Ping(self) -> TestResult :
        response: ControlPacket = self.pod.WriteRead('PING')

        if (response.command_number != 2) :
            return TestResult(False, 'Packet has an incorrect command number.')

        return TestResult(True)
    
    def Type(self) -> TestResult :
        response: ControlPacket = self.pod.WriteRead('TYPE')

        if (response.command_number != 8) :
            return TestResult(False, 'Packet has an incorrect command number.')

        return TestResult(True)
       
    def FirmVer(self) -> TestResult :
        response: ControlPacket = self.pod.WriteRead('FIRMWARE VERSION')

        if (response.command_number != 12) :
            return TestResult(False, 'Packet has an incorrect command number.')

        payload: tuple | None = response.payload

        if payload is None :
            return TestResult(False,'No return payload.')
        
        if (len(payload) != 3) :
            return TestResult(False,'Return payload has incorrect length.')

        return TestResult(True)

    def Mode(self) -> TestResult :
        #set pc control mode.
        set_response: ControlPacket = self.pod.WriteRead('SET MODE', 1)
        get_response: ControlPacket = self.pod.WriteRead('GET MODE')

        if (set_response.command_number != 132 or get_response.command_number != 133) :
            return TestResult(False, 'Some packet has an incorrect command number.')
        
        if (set_response.payload != (1,)):
            return TestResult(False, 'Failed to correctly set mode as PC control.')

        if (get_response.payload != set_response.payload):
            return TestResult(False, 'Set value does not match reported value.')
        
        #set schedule mode.
        set_response: ControlPacket = self.pod.WriteRead('SET MODE', 2)

        #if the motor speed was set manually or something before, 
        #setting schedule mode causes the lcd to set the motor speed.
        #we try to read a 201 packet and throw it into the abyss!
        try:
            self.pod.ReadPODpacket()
        except Exception:
            pass

        get_response: ControlPacket = self.pod.WriteRead('GET MODE')

        if (set_response.payload != (2,)):
            return TestResult(False, 'Failed to correctly set mode as internal schedule.')

        #make sure set and get values match again. important to test in case that
        #device is reporting the same mode each time.
        if (get_response.payload != set_response.payload):
            return TestResult(False, 'Set value does not match reported value.')

        #set manual mode.
        set_response: ControlPacket = self.pod.WriteRead('SET MODE', 0)
        
        if (set_response.payload != (0,)):
            return TestResult(False, 'Failed to correctly set mode as manual.')

        return TestResult(True)

    def Motor(self) -> TestResult :
        #test turning motor on
        prev_get_response: ControlPacket =  self.pod.WriteRead('GET MOTOR STATE')
        set_response: ControlPacket =  self.pod.WriteRead('SET MOTOR STATE', 1)
        get_response: ControlPacket =  self.pod.WriteRead('GET MOTOR STATE')

        if (set_response.command_number != 146 or get_response.command_number != 147) :
            return TestResult(False, 'Some packet when testing state has an incorrect command number.')

        if (get_response.payload != (1,)):
            return TestResult(False, 'Failed to turn on motor.')

        if (prev_get_response.payload != set_response.payload):
            return TestResult(False, 'Set motor state value does not match previously reported motor state value.')

        #test 100% speed.
        prev_get_response: ControlPacket =  self.pod.WriteRead('GET MOTOR SPEED')
        set_response: ControlPacket = self.pod.WriteRead('SET MOTOR SPEED', 100)
        get_response: ControlPacket = self.pod.WriteRead('GET MOTOR SPEED')
        
        if (set_response.command_number != 136 or get_response.command_number != 137) :
            return TestResult(False, 'Some packet in setting and getting motor speed has an incorrect command number.')
        
        if (get_response.payload != (100,)):
            return TestResult(False, 'Failed to correctly set motor speed to 100%.')
        
        if (prev_get_response.payload != set_response.payload):
            return TestResult(False, 'Set value does not match previously reported value.')
        
        #test setting motor direction.
        set_response: ControlPacket = self.pod.WriteRead('SET MOTOR DIRECTION', 0)
        get_response: ControlPacket = self.pod.WriteRead('GET MOTOR DIRECTION')

        if (set_response.command_number != 128 or get_response.command_number != 129) :
            return TestResult(False, 'Some packet has an incorrect command number.')
        
        if (set_response.payload != (0,)):
            return TestResult(False, 'Failed to correctly set motor direction as clockwise.')
        
        #make sure set and get values match.
        if (get_response.payload != set_response.payload):
            return TestResult(False, 'Set value does not match reported value.')
        
        #set counterclockwise.
        set_response: ControlPacket = self.pod.WriteRead('SET MOTOR DIRECTION', 1)
        get_response: ControlPacket = self.pod.WriteRead('GET MOTOR DIRECTION')

        if (set_response.payload != (1,)):
            return TestResult(False, 'Failed to correctly set motor direction as counterclockwise.')

        #make sure set and get values match again. important to test in case that
        #device is reporting the same direction each time.
        if (get_response.payload != set_response.payload):
            return TestResult(False, 'Set value does not match reported value.')

        #test random reverse params.

        #tuple is (base time, variable time).
        times: tuple[int] = tuple(random.sample(range(1,3), 2))

        set_response: ControlPacket = self.pod.WriteRead('SET REVERSE PARAMS', times)
        get_response: ControlPacket = self.pod.WriteRead('GET REVERSE PARAMS')

        if (set_response.command_number != 144 or get_response.command_number != 145) :
            return TestResult(False, 'Some packet has an incorrect command number.')
        
        if (get_response.payload != times) :
            return TestResult(False, 'Unable to correctly set random reverse parameters.')
        
        #test random reverse itself.
        set_response: ControlPacket = self.pod.WriteRead('SET RANDOM REVERSE', 1)
        
        try:
            reverse_event : ControlPacket = self.pod.ReadPODpacket(timeout_sec = sum(times))

            if (reverse_event.command_number != 143) :
                return TestResult(False, 'REVERSE TIME EVENT packet contained wrong command number.')
            
            #packet  payload contains time until next reverse. verify that this is true.
            reverse_event : ControlPacket = self.pod.ReadPODpacket(timeout_sec = reverse_event.payload[0])

        except Exception:
            return TestResult(False, 'Did not recieve REVERSE TIME EVENT packet within expected time frame.')

        get_response: ControlPacket = self.pod.WriteRead('GET RANDOM REVERSE')
        
        if (set_response.command_number != 150 or get_response.command_number != 151) :
            return TestResult(False, 'Some command had incoreect number when getting/setting random reverse.')
        
        if (get_response.payload == (0,)) :
            return TestResult(False, 'Failed to correctly set random reverse on.')
        
        set_response: ControlPacket = self.pod.WriteRead('SET RANDOM REVERSE', 0)
        get_response: ControlPacket = self.pod.WriteRead('GET RANDOM REVERSE')

        if (get_response.payload != (0,)) :
            return TestResult(False, 'Failed to correctly set random reverse off.')

        #test 0% speed.
        prev_get_response: ControlPacket =  self.pod.WriteRead('GET MOTOR SPEED')
        set_response: ControlPacket = self.pod.WriteRead('SET MOTOR SPEED', 0)
        get_response: ControlPacket = self.pod.WriteRead('GET MOTOR SPEED')
        
        if (get_response.payload != (0,)):
            return TestResult(False, 'Failed to correctly set motor speed to 0%.')

        if (set_response.payload != prev_get_response.payload):
            return TestResult(False, 'Set value does not match reported value from GET MOTOR SPEED.')
        
        #test 5 random speeds in-between 0 and 100 (non-inclusive).
        for speed in random.sample(range(1, 100), k=5):
            self.pod.WriteRead('SET MOTOR SPEED', speed)
            get_response: ControlPacket = self.pod.WriteRead('GET MOTOR SPEED')
            
            if (get_response.payload != (speed,)):
                return TestResult(False, f'Failed to correctly set motor speed to {speed}%.')

        #test turning motor off
        prev_get_response: ControlPacket =  self.pod.WriteRead('GET MOTOR STATE')
        set_response: ControlPacket =  self.pod.WriteRead('SET MOTOR STATE', 0)
        get_response: ControlPacket =  self.pod.WriteRead('GET MOTOR STATE')

        if (get_response.payload != (0,)):
            return TestResult(False, 'Failed to turn off motor.')

        if (prev_get_response.payload != set_response.payload):
            return TestResult(False, 'Set motor state value does not match previously reported motor state value.')

        return TestResult(True)
   
    def Time(self) -> TestResult :
        #since we just test length, set it to a random static value.
        response: ControlPacket = self.pod.WriteRead('SET TIME', (0, 5, 2, 1, 1, 11, 2))

        if (response.command_number != 140) :
            return TestResult(False, 'Packet has an incorrect command number.')
        
        payload: tuple | None = response.payload

        if payload is None :
            return TestResult(False,'No return payload.')

        if (len(payload) != 7) :
            return TestResult(False,'Return payload has incorrect length.')

        return TestResult(True)
            
    def Schedule(self) -> TestResult :
        #test random schedule for each day.
        for day in range(7):
            power_choices: list[int] = [ random.randint(0,1) for _ in range(24) ]
            speed_choices: list[int] = [ random.randint(0, 100) for _ in range(24) ]
            schedule: list[int] = Pod8229.CodeDaySchedule(power_choices, speed_choices)

            send_payload: tuple[int] = tuple([day] + schedule)

            set_response: ControlPacket = self.pod.WriteRead('SET DAY SCHEDULE', send_payload)

            get_response: ControlPacket = self.pod.WriteRead('GET DAY SCHEDULE', day)

            get_response_payload: dict[str, tuple[int]] = get_response.payload

            if (get_response.command_number != 142 or set_response.command_number != 141) :
                return TestResult(False, 'Some packet has an incorrect command number.')
            
            if (get_response_payload['Hour'] != tuple(power_choices) or get_response_payload['Speed'] != tuple(speed_choices)) :
                return TestResult(False, 'Mismatch between sent and recieved schedules.')

        self._SetDefaultSchedule()

        return TestResult(True)

from Testing.T_Morelia.TestProtocol import RunningTests, TestResult
from Morelia.Devices.SerialPorts import PortIO, FindPorts

# authorship
__author__      = "James Hurd"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert", "James Hurd"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class T_PortIO :

    def __init__(self, baudrate: int = 9600) -> None :
        self.baudrate : int = baudrate
        
    # ---------------------------------------------------------------------------------------------------------
    def RunTests(self, printTests: bool = True) -> tuple[int, int]:
        """Run all tests on for Morelia.Devices.SerialPorts.SerialComm

        Args:
            printTests (bool, optional): Make True to print the test results and messages. Defaults to True.

        Returns:
            tuple[int,int]: First item is the number of passed tests. Last item is the total number of tests
        """

        tests = { 
            '1. OpenClose:\t\t': self.OpenClose,
            '2. SetBaudRate:\t\t': self.SetBaudRate,
            '3. Flush:\t\t': self.Flush,
            '4. Ping:\t\t': self.Ping,
            '5. ReadLines:\t\t': self.ReadLines,
            '6. ReadUntil:\t\t': self.ReadUntil
        }

        return RunningTests.RunTests(tests, 'PortIO', printTests=printTests)
    # ---------------------------------------------------------------------------------------------------------

    def OpenClose(self, port: str | int | None = None, forbidden: list[str] = []) -> TestResult : 

        if (port is None) :
            print('~~~~~~~~~~ PortIO ~~~~~~~~~~')
            port: str = FindPorts.ChoosePort(forbidden)
            print('~~~~~~~~~~~~~~~~~~~~~~~~~~~~')

        io: PortIO = PortIO(port, self.baudrate)
        io.OpenSerialPort(port)

        if( not io.IsSerialOpen() ) :
            return TestResult(False, 
                'Failed to detect port as open. Either an error in opening the port, or it is incorrectly being reported as closed.')
        
        if( io.GetPortName() is None ) :
            return TestResult(False, "Unable to get port name.")

        io.CloseSerialPort()

        if ( not io.IsSerialClosed() ) :
            return TestResult(False, 
                'Failed to detect port as closed. Either an error in closing the port, or it is incorrectly being reported as opened.')

        if ( io.GetPortName() is not None ) :
            return TestResult(False, 'Got a name for a closed port.')

        return TestResult(True)

    def SetBaudRate(self) -> TestResult :
        io: PortIO = PortIO('TEST', self.baudrate)
        if( not io.SetBaudrate(self.baudrate) ):
            return TestResult(False, 'Failed to set baud rate.')
        return TestResult(True)

    def Flush(self) -> TestResult :
        io: PortIO = PortIO('TEST', self.baudrate)
        if( not io.Flush() ):
            return TestResult(False, 'Failed to flush buffers.')
        return TestResult(True)

    def Ping(self) -> TestResult :
        io: PortIO = PortIO('TEST', self.baudrate)
        test_data: bytes = b'ping'
        io.Write(test_data)
        read_data: bytes | None = io.Read(4) 

        if (read_data is None) :
            return TestResult(False, 'Failed to read data, port is closed.')
        elif (not read_data == test_data) :
            return TestResult(False, 'Ping failed, read data does not match what was sent.')

        return TestResult(True)

    def ReadLines(self) -> TestResult :
        io: PortIO = PortIO('TEST', self.baudrate)
        test_data: tuple[bytes] = (b'ping1\n', b'ping2\n')
        io.Write(test_data[0] + test_data[1])
        read_data: tuple[bytes] = io.ReadLine(), io.ReadLine()
        
        if not all(read_data):
            return TestResult(False, 'Failed to read data from port at some point.')

        match read_data[0] == test_data[0], read_data[1] == read_data[1]:
            case False, False:
                return TestResult(False, 'Both lines incorrect.')
            case True, False:
                return TestResult(False, 'First line incorrect.')
            case False, True:
                return TestResult(False, 'Second line incorrect.')
            case True, True:
                return TestResult(True)

    def ReadUntil(self) -> TestResult :
        io: PortIO = PortIO('TEST', self.baudrate)
        delim : bytes = b'STOP'
        good_data: bytes = b'good stuff'
        bad_data: bytes = b'bad stuff'
        io.Write(good_data + delim + bad_data)
        read_data = io.ReadUntil(delim)
        
        if (read_data is None) :
            return TestResult(False, 'Failed to read data from port.')

        if (not read_data == good_data + delim) :
            return TestResult(False, 'Incorrect Read.')

        return TestResult(True)

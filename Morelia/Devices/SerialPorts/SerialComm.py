# enviornment imports 
from    serial import Serial, serial_for_url
import  platform
import  time

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert", "James Hurd"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class PortIO : 
    """
    COM_io handles serial communication (read/write) using COM ports. 

    Attributes:
        __serialInst (Serial): Instance-level serial COM port.
    """

    # ====== DUNDER METHODS ======

    def __init__(self, port: str|int, baudrate:int=9600) -> None :
        """Runs when the object is constructed. It initialized the __serialInst to a given COM port with \
        a set baudrate.

        Args:
            port (str | int): String of the serial port to be opened. 
            baudrate (int, optional): Integer baud rate of the opened serial port. Defaults to 9600.
        """

        if (port == 'TEST') :

            self.__serialInst : Serial = serial_for_url('loop://')

        else:

            # initialize port 
            self.__serialInst : Serial = Serial()
            # open port  
            self.OpenSerialPort(port, baudrate=baudrate)

    def __del__(self) -> None :
        """Runs when the object is destructed. It closes the serial port, if open."""
        # close port 
        self.CloseSerialPort()

    # ====== PRIVATE METHODS ======
        
    def __BuildPortName(self, port: str|int) -> str :
        """Converts the port parameter into the "COM"+<number> format for Windows or \
        "/dev/tty..."+<number> for Linux.

        Args:
            port (str | int): Name of a COM port. Can be an integer or string.

        Returns:
            str: Name of the COM port.
        """
        name = None
        # is 'port' the port number? 
        if (isinstance(port, int)) : 
            # build port name
            if (platform.system() == 'Windows') :
                name = 'COM' + str(port)
            if (platform.system() == 'Linux') :
                name = '/dev/tty' + str(port)
        elif (isinstance(port, str)): 
            # is 'port' the port name or just the number?
            if port.startswith('COM'):
                # assume that 'port' is the full name  
                name = port.split(' ')[0]
            elif port.startswith('/dev/tty'):
                # /dev/tty is for Linux
                # assume that 'port' is the full name  
                name = port.split(' ')[0]
            else : 
                # assume that 'port' is just the number 
                name = 'COM' + port
        # end 
        return(name)

    # ====== PUBLIC METHODS ======

    # ----- BOOL CHECKS -----

    def IsSerialOpen(self) -> bool : 
        """Returns True if the serial instance port is open, false otherwise.

        Returns:
            bool: True if the COM port is open, False otherwise. 
        """
        # true if serial port is open, false otherwise 
        return(self.__serialInst.isOpen())

    def IsSerialClosed(self) -> bool :
        """Returns False if the serial instance port is open, True otherwise.

        Returns:
            bool:True if the COM port is closed, False otherwise. 
        """
        # true if serial port is closed, false otherwise 
        return(not self.IsSerialOpen())

    # ----- SERIAL MANAGEMENT -----

    def CloseSerialPort(self) -> None :
        """Closes the instance serial port if it is open."""
        # close port if open 
        if(self.IsSerialOpen()) :
            self.__serialInst.close()

    def OpenSerialPort(self, port: str|int, baudrate:int=9600) -> None : 
        """First, it closes the serial port if it is open. Then, it opens a serial port with a set \
        baud rate. 

        Args:
            port (str | int): String of the serial port to be opened. 
            baudrate (int, optional): Integer baud rate of the opened serial port. Defaults to 9600.

        Raises:
            Exception: Port does not exist.
        """
        # close current port if it is open
        if(self.IsSerialOpen()) : 
            self.CloseSerialPort()
        # get name 
        name = self.__BuildPortName(port)
        # if the 'Name' is not None
        if(name) : 
            # initialize and open serial port 
            self.__serialInst.baudrate = baudrate
            self.__serialInst.port = name
            self.__serialInst.open()
        else : 
            # throw an error 
            raise Exception('Port does not exist.')

    def SetBaudrate(self, baudrate: int) -> bool :
        """Sets the baud rate of the serial port

        Args:
            baudrate (int): Baud rate, or signals per second. 

        Returns:
            bool: True if the baudrate was set, False otherwise.
        """
        # port must be open 
        if(self.IsSerialOpen()) : 
            # set baudrate 
            self.__serialInst.baudrate = baudrate
            return(True) 
        else : 
            return(False)

    def Flush(self) -> bool : 
        """Reset the input and output serial buffer.

        Returns:
            bool: True of the buffers are flushed, False otherwise.
        """
        if(self.IsSerialOpen()) : 
            self.__serialInst.reset_input_buffer()
            self.__serialInst.reset_output_buffer()
            return(True) 
        else : 
            return(False)

    # ----- GETTERS -----

    def GetPortName(self) -> str|None : 
        """Gets the name of the open port.

        Returns:
            str|None: If the serial port is open, it will return a string of the port's name. \
                If the port is closed, it will return None.
        """
        # return the port name if a port is open
        if(self.IsSerialOpen()) : 
            return(self.__serialInst.name) 
        # otherwise return nothing
        else :
            return(None)

    # ----- INPUT/OUTPUT -----

    def Read(self, numBytes: int, timeout_sec: int|float = 5) -> bytes|None :
        """Reads a specified number of bytes from the open serial port.

        Args:
            numBytes (int): Integer number of bytes to read.
            timeout_sec (int|float, optional): Time in seconds to wait for serial data. \
                Defaults to 5. 
        
        Raises:
            Exception: Timeout for serial read.

        Returns:
            bytes|None: If the serial port is open, it will return a set number of read bytes. \
                If it is closed, it will return None.
        """
        # do not continue of serial is not open 
        if(self.IsSerialClosed()) :
            return(None)
        # wait until port is in waiting, then read 
        t = 0.0
        while (t < timeout_sec) :
            ti = (round(time.time(),9)) # initial time (sec)          
            if self.__serialInst.in_waiting : 
                # read packet
                return(self.__serialInst.read(numBytes) )
            t += (round(time.time(),9)) - ti
        raise TimeoutError('[!] Timeout for serial read after '+str(timeout_sec)+' seconds.')


    def ReadLine(self) -> bytes|None :
        """Reads until a new line is read from the open serial port.

        Returns:
            bytes|None: If the serial port is open, it will return a complete read line. \
                If closed, it will return None.
        """
        # do not continue of serial is not open 
        if(self.IsSerialClosed()) :
            return(None)
        # wait until port is in waiting, then read line 
        while True :
            if self.__serialInst.in_waiting : 
                # read packet up to  and including newline ('\n')
                return(self.__serialInst.readline())
    
    def ReadUntil(self, eol: bytes) -> bytes|None:
        """Reads until a set character from the open serial port.

        Args:
            eol (bytes): end-of-line character.

        Returns:
            bytes|None: If the serial port is open, it will return a read line ending in eol. \
                If closed, it will return None.
        """
        # do not continue of serial is not open 
        if(self.IsSerialClosed()) :
            return(None)
        # wait until port is in waiting, then read 
        while True :
            if self.__serialInst.in_waiting : 
                # read packet until end of line (eol) character 
                return(self.__serialInst.read_until(eol) )

    def Write(self, message: bytes) -> None : 
        """Write a set message to the open serial port. 

        Args:
            message (bytes): byte string containing the message to write.
        """
        # write message to open port 
        if(self.IsSerialOpen()) : 
            self.__serialInst.write(message)

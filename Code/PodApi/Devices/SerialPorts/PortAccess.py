# enviornment imports 
from    serial.tools.list_ports import comports
import  platform

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class FindPorts : 
    """Contains methods for the user to view and select a serial port.
    """

    @staticmethod
    def GetAllPortNames() -> list[str] : 
        """Finds all the available COM ports on the user's computer and appends them to an \
        accessible list. 

        Returns:
            list[str]: List containing the names of available COM ports.
        """
        # get all COM ports in use
        allPorts = comports()
        # convert COM ports to string list 
        portList = []
        for port in allPorts:
            portList.append(str(port))
        # end
        return(portList)

    @staticmethod
    def GetSelectPortNames(forbidden:list[str]=[]) -> list[str] : 
        """Gets the names of all available ports.

        Args:
            forbidden (list[str], optional): List of port names that the user should \
                not use. This may be because these ports are already in use or that \
                the port is not a POD device. Defaults to [].

        Returns:
            list[str]: List of port names.
        """
        # remove forbidden ports
        portList = [x for x in FindPorts.GetAllPortNames() if x not in forbidden]
        # check if the list is empty 
        if (len(portList) == 0):
            # print error and keep trying to get ports
            print('[!] No ports in use. Please plug in a device.')
            while(len(portList) == 0) : 
                portList = [x for x in FindPorts.GetAllPortNames() if x not in forbidden]
        # return port
        return(portList)

    @staticmethod
    def ChoosePort(forbidden:list[str]=[]) -> str : 
        """Systems checks user's Operating System, and chooses ports accordingly.

        Args:
            forbidden (list[str], optional): List of port names that the user should \
                not use. This may be because these ports are already in use or that \
                the port is not a POD device. Defaults to [].
        Returns:
            str: String name of the port.
        """
        # checks user's Operating System.
        match platform.system() :
            case 'Linux'    : return FindPorts._ChoosePortLinux(forbidden)
            case 'Windows'  : return FindPorts._ChoosePortWindows(forbidden)
            case    _       : raise Exception('[!] Platform is not supported. Please use a Windows or Linux system.')
    
    @staticmethod
    def _ChoosePortLinux(forbidden:list[str]=[]) -> str : 
        """User picks Serial port in Linux.

        Args:
            forbidden (list[str], optional): List of port names that the user should \
                not use. This may be because these ports are already in use or that \
                the port is not a POD device. Defaults to [].
                
        Returns:
            str: String name of the port.
        """
        portList = FindPorts.GetSelectPortNames(forbidden)
        print('Available Serial Ports: '+', '.join(portList))
        choice = input('Select port: /dev/tty')
        if(choice == ''):
            print('[!] Please choose a Serial port.')
            return(FindPorts._ChoosePortLinux(forbidden))
        else:
            # search for port in list
            for port in portList:
                if port.startswith('COM'+choice):
                    return(port)
                if port.startswith('/dev/tty'+choice):
                    return(port)
            # if return condition not reached...
            print('[!] tty'+choice+' does not exist. Try again.')
            return(FindPorts._ChoosePortLinux(forbidden))

    @staticmethod
    def _ChoosePortWindows(forbidden:list[str]=[]) -> str :
        """User picks COM port in Windows.

        Args:
            forbidden (list[str], optional): List of port names that the user should \
                not use. This may be because these ports are already in use or that \
                the port is not a POD device. Defaults to [].
        Returns:
            str: String name of the port.
        """
        portList = FindPorts.GetSelectPortNames(forbidden)
        print('Available COM Ports: '+', '.join(portList))
        # request port from user
        choice = input('Select port: COM')
        # choice cannot be an empty string
        if(choice == ''):
            print('[!] Please choose a COM port.')
            return(FindPorts._ChoosePortWindows(forbidden))
        else:
            # search for port in list
            for port in portList:
                if port.startswith('COM'+choice):
                    return(port)
            # if return condition not reached...
            print('[!] COM'+choice+' does not exist. Try again.')
            return(FindPorts._ChoosePortWindows(forbidden))

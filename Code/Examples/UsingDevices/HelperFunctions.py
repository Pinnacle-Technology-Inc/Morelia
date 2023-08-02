# add directory path to code 
import Path 
Path.AddAPIpath()

# local imports
from Devices import COM_io, POD_Basics
from Packets import Packet

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

def ChoosePort() -> str :
    """Asks the user to choose a COM port. This is used for \
    Windows systems.

    Returns:
        str: String with the COM port name. 
    """
    # get ports
    portList: list[str] = COM_io.GetCOMportsList()
    print('Available COM Ports: '+', '.join(portList))
    # request port from user
    choice: str = input('Select port: COM')
    # search for port in list
    for port in portList:
        if port.startswith('COM'+choice):
            return(port)
    print('[!] COM'+choice+' does not exist. Try again.')
    return(ChoosePort())

def Write(pod: POD_Basics, cmd: str | int, payload: int | bytes | tuple[int | bytes] = None) : 
    """Writes a command packet to a POD device and prints the packet.

    Args:
        pod (POD_Basics): POD device. 
        cmd (str | int): Command name or number.
        payload (int | bytes | tuple[int  |  bytes], optional): Optional payload for the \
            command. Defaults to None.
    """
    write: Packet = pod.WritePacket(cmd, payload)
    data:  dict = write.TranslateAll()
    print('Write:\t', data)

def Read(pod: POD_Basics) : 
    """Reads and prints a packet from a POD device.

    Args:
        pod (POD_Basics): _description_
    """
    read: Packet = pod.ReadPODpacket()
    data: dict = read.TranslateAll()
    print('Read:\t', data)

def RunCommand(pod: POD_Basics, cmd: str | int, payload: int | bytes | tuple[int | bytes] = None) :
    """Writes and reads a packet from a POD device and prints the results.

    Args:
        pod (POD_Basics): POD device. 
        cmd (str | int): Command name or number.
        payload (int | bytes | tuple[int  |  bytes], optional): Optional payload for the \
            command. Defaults to None.
    """
    Write(pod,cmd,payload)
    Read(pod)
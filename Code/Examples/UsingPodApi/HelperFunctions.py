""" This python script contains functions used by the Using_<POD device> \
    scripts to connect to, write to, and read from a POD device.
"""

# add directory path to code 
import Path 
Path.AddAPIpath()

# local imports
from Morelia.Devices     import Pod
from Morelia.Packets     import Packet

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

def Write(pod: Pod, cmd: str | int, payload: int | bytes | tuple[int | bytes] = None) : 
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

def Read(pod: Pod) : 
    """Reads and prints a packet from a POD device.

    Args:
        pod (POD_Basics): _description_
    """
    read: Packet = pod.ReadPODpacket()
    data: dict = read.TranslateAll()
    print('Read:\t', data)  


def RunCommand(pod: Pod, cmd: str | int, payload: int | bytes | tuple[int | bytes] = None) :
    """Writes and reads a packet from a POD device and prints the results.

    Args:
        pod (POD_Basics): POD device. 
        cmd (str | int): Command name or number.
        payload (int | bytes | tuple[int  |  bytes], optional): Optional payload for the \
            command. Defaults to None.
    """
    Write(pod,cmd,payload)
    Read(pod)

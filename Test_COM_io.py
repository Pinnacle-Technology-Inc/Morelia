from Serial_InOut import COM_io
from BasicPodProtocol import POD_Basics

# get port list 
portList = COM_io.GetCOMportsList()

# check if the list is empty 
if (len(portList) == 0):
    raise Exception('[!] No COM ports in use.')
# use single option 
elif (len(portList) == 1): 
    phrase = portList[0].split(' ')
    portUse = phrase[0]
# choose port 
else:
    # request port from user
    comNum = input('Select port: COM')
    # search for port
    portUse = None
    for port in portList:
        if port.startswith('COM'+comNum):
            portUse = 'COM' + comNum 
    # check if port exists
    if portUse==None : 
        raise Exception('[!] COM port does not exist.')

# create COM object 
pod = POD_Basics(portUse)
print('serial port in use:', pod.GetPortName())

# # # PING 
# # cmd = 2
# # print('COMMAND:', cmd)
# # if(pod.WritePacket(cmd)):
# #     print('RESPONSE:', pod.ReadPodPacket())
# # else:
# #     print('Command ' + str(cmd) + ' write failed')

# # # STREAM
# # cmd = 6
# # payload = bytes.fromhex('3030')
# # print('COMMAND:', cmd)
# # if(pod.WritePacket(cmd, payload)):
# #     print('RESPONSE:', pod.ReadPodPacket())
# # else:
# #     print('Command ' + str(cmd) + ' write failed')

cmd = bytes.fromhex('30303042')
length = bytes.fromhex('30303634') 
csm = POD_Basics.Checksum(cmd+length)

msg = pod.STX() + cmd + length + csm + pod.ETX() # 1 + 4 + 4 + 2 + 1
print(msg)

def UnpackPodCommand(msg, MinPacketBytes=8) : 
    # get number of bytes in message
    packetBytes = len(msg)
    # create dict
    msg_unpacked = {
        'Command Number' : msg[1:5],                            # four bytes after STX
        'Checksum'       : msg[(packetBytes-3):(packetBytes-1)] # two bytes before ETX
    }
    # add packet if available 
    if( (packetBytes - MinPacketBytes) > 0) : 
        msg_unpacked['Packet'] = msg[5:(packetBytes-3)]         # remaining bytes between command number and checksum 
          
    # return unpacked POD command
    return(msg_unpacked)

msg_split = UnpackPodCommand(msg)
print(msg_split)

msg_split = pod.UnpackPodCommand(msg)
print(msg_split)

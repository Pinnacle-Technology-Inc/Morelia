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

# PING 
cmd = 2
print('COMMAND:', cmd)
if(pod.WritePacket(cmd)):
    print('RESPONSE:', pod.ReadPodPacket())
else:
    print('Command ' + str(cmd) + ' write failed')

# STREAM
cmd = 6
payload = bytes.fromhex('3030')
print('COMMAND:', cmd)
if(pod.WritePacket(cmd, payload)):
    print('RESPONSE:', pod.ReadPodPacket())
else:
    print('Command ' + str(cmd) + ' write failed')
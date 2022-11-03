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

####################################################################################################################

cmd = bytes.fromhex('30303042')
length = bytes.fromhex('30303634') 
csm = pod.Checksum(cmd+length)
blength = pod.AsciiBytesToInt(length)
binaryMsg = bytes.fromhex('00')
for i in range(blength-1) : 
    binaryMsg = binaryMsg + bytes.fromhex('00') 
binaryCsm = pod.Checksum(binaryMsg)
msgPOD = pod.STX() + cmd + length + csm + pod.ETX()
msg = msgPOD + binaryMsg + binaryCsm + pod.ETX()
# print(msg)

msgDict = pod.UnpackPodCommand_VariableBinary(msg)
print(msgDict)

msgPODDict = pod.UnpackPodCommand_Standard(msgPOD)
print(msgPODDict)

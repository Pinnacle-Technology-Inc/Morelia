from SerialCommunication import COM_io
from BasicPodProtocol import POD_Basics
from PodDevice_8206HR import POD_8206HR
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

# verify communication link
wrt = pod.WritePacket('PING')
red = pod.ReadPODpacket()
if(wrt == red):
    print('Communication successful: ', red)
else:
    raise Exception('Communication Failiure: ', red)
    


########## TESTING ##########################################################################################################
print('\n\n')

pod8206HR = POD_8206HR(portUse)

# pod8206HR.WritePacket('GET FILTER CONFIG')
# print(pod8206HR.TranslatePODpacket(pod8206HR.ReadPODpacket()))

pod8206HR.WritePacket(6, bytes.fromhex('3031')) # turn on stream 
for i in range(10) :
    msg  = pod8206HR.ReadPODpacket()
    Tmsg = pod8206HR.TranslatePODpacket(msg)
    print(Tmsg)
pod8206HR.WritePacket(6, bytes.fromhex('3030')) # turn off stream # this doesnt work??? It just keeps on streaming....
msg  = pod8206HR.ReadPODpacket()
Tmsg = pod8206HR.TranslatePODpacket(msg)
print(Tmsg)

print('\n\n')
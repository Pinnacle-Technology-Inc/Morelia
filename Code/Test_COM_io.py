from SerialCommunication import COM_io
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

# verify communication link
wrt = pod.WritePacket('PING')
red = pod.ReadPODpacket_Standard()
if(wrt == red):
    print('Communication successful')
else:
    print('Communication Failiure')


########## TESTING ##########################################################################################################
print('\n\n')

print('\n\n')
from SerialCommunication import COM_io
from BasicPodProtocol import POD_Basics
from PodDevice_8206HR import POD_8206HR
from PodCommands import POD_Commands
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
# delete pod object
del pod

########## TESTING ##########################################################################################################
print('\n\n')

# DEMO 

# 1. creating pod devices & device counters 
def ex1():
    # create a pod device by passing the appropriate serial port 
    pod1 = POD_Basics(portUse)
    print('Number of POD devices:\t', POD_Basics.GetNumberOfPODDevices())
    # creating new pod objects increments counter 
    pod2 = POD_Basics(portUse)
    pod3 = POD_Basics(portUse)
    print('Number of POD devices:\t', POD_Basics.GetNumberOfPODDevices())
    # creating subclasses of pod basics also increments counter 
    pod4 = POD_8206HR(portUse)
    print('Number of POD devices:\t', POD_Basics.GetNumberOfPODDevices())
    # deleting pod devices decrements counter
    del pod1
    del pod2
    del pod3
    del pod4
    print('Number of POD devices:\t', POD_Basics.GetNumberOfPODDevices())
# ex1()

# 2. command access
def ex2():
    # create a pod device by passing the appropriate serial port 
    podB = POD_Basics(portUse)
    podR = POD_8206HR(portUse)
    # print initialized commands  
    print('Basic commands:\n', podB.GetDeviceCommands(),'\n')
    print('8206HR commands:\n',podR.GetDeviceCommands(),'\n')

    # create command dict object
    cmds = POD_Commands()
    print('8206HR commands:\n',cmds.GetCommands(),'\n')
ex2()



# conversions
# command dict access (add/remove)
# write messages
# read messages 
# unpack and translate messages





print('\n\n')

# pod8206HR = POD_8206HR(portUse)

# # pod8206HR.WritePacket('GET FILTER CONFIG')
# # print(pod8206HR.TranslatePODpacket(pod8206HR.ReadPODpacket()))

# pod8206HR.WritePacket(6, bytes.fromhex('3031')) # turn on stream 
# for i in range(10) :
#     msg  = pod8206HR.ReadPODpacket()
#     Tmsg = pod8206HR.TranslatePODpacket(msg)
#     print(Tmsg)
# pod8206HR.WritePacket(6, bytes.fromhex('3030')) # turn off stream # this doesnt work??? It just keeps on streaming....
# msg  = pod8206HR.ReadPODpacket()
# Tmsg = pod8206HR.TranslatePODpacket(msg)
# print(Tmsg)

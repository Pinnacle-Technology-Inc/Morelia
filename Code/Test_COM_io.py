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

# 2. command access
def ex2():
    # create command dict object
    cmds = POD_Commands()
    print('POD_Commands initialization:\n',cmds.GetCommands(),'\n')
    # adding commands to dict 
    cmds.AddCommand(991,'TEST1',199,919,True)
    cmds.AddCommand(992,'TEST2',299,929,True)
    cmds.AddCommand(993,'TEST3',299,939,True)
    print('POD_Commands (Add):\n',cmds.GetCommands(),'\n')
    # removing command from dict 
    cmds.RemoveCommand('TEST3')
    print('POD_Commands (Rem):\n',cmds.GetCommands(),'\n')
    # helpful functions 
    print('TEST1 exists:\t',    cmds.DoesCommandExist('TEST1'))
    print('TEST1 number:\t',    cmds.CommandNumberFromName('TEST1'))
    print('TEST1 argument:\t',  cmds.ArgumentBytes('TEST1'))
    print('TEST1 return:\t',    cmds.ReturnBytes('TEST1'))
    print('TEST1 binary:\t',    cmds.IsCommandBinary('TEST1'))

# 3. initialization of commands 
def ex3():
    # create a pod device by passing the appropriate serial port 
    podB = POD_Basics(portUse)
    podR = POD_8206HR(portUse)
    # print initialized commands  
    print('Basic commands:\n', podB.GetDeviceCommands(),'\n')
    print('8206HR commands:\n',podR.GetDeviceCommands(),'\n')

# 4. read and write 
def ex4():
    # create pod device object 
    podR = POD_8206HR(portUse)
    # Write and Read standard POD message with no packet 
    w = podR.WritePacket('PING')
    print('Write (PING):\t', w, podR.UnpackPODpacket(w), podR.TranslatePODpacket(w))
    r = podR.ReadPODpacket()
    print('Read (PING):\t', r, podR.UnpackPODpacket(r), podR.TranslatePODpacket(r))
    print('\n')
    # Write and Read standard POD message with a packet 
    w = podR.WritePacket('GET LOWPASS', podR.IntToAsciiBytes(0,2)) # 0 = EEG1
    print('Write (GET LOWPASS):\t', w, podR.UnpackPODpacket(w), podR.TranslatePODpacket(w))
    r = podR.ReadPODpacket()
    print('Read (GET LOWPASS):\t', r, podR.UnpackPODpacket(r), podR.TranslatePODpacket(r))
    print('\n')
    # Write and Read binary 
    w = podR.WritePacket('STREAM', podR.IntToAsciiBytes(1,2)) # 1 = ON
    print('Write (STREAM):\t', podR.TranslatePODpacket(w))
    for i in range(10) : 
        r = podR.ReadPODpacket()
        print('Read (BINARY4 DATA):\t', podR.TranslatePODpacket(r))
    print('\n')
    w = podR.WritePacket('STREAM', podR.IntToAsciiBytes(0,2)) # 0 = OFF
    # # Try to get a response after stream 
    # for i in range(10):
    #     w = podR.WritePacket('PING')
    #     print('Write (PING):\t', podR.TranslatePODpacket(w))
    #     r = podR.ReadPODpacket()
    #     print('Read (PING):\t',podR.TranslatePODpacket(r))

# run demos
ex1()
print('~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~')
ex2()
print('~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~')
ex3()
print('~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~')
ex4()

# conversions


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

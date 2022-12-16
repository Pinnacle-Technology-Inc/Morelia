from SerialCommunication    import COM_io
from BasicPodProtocol       import POD_Basics
from PodDevice_8206HR       import POD_8206HR
from PodCommands            import POD_Commands
from Setup_8206HR           import Setup_8206HR

# # get port list 
# portList = COM_io.GetCOMportsList()
# print('Ports:\t',portList)
# # check if the list is empty 
# if (len(portList) == 0):
#     raise Exception('[!] No COM ports in use.')
# # use single option 
# elif (len(portList) == 1): 
#     phrase = portList[0].split(' ')
#     portUse = phrase[0]
# # choose port 
# else:
#     # request port from user
#     comNum = input('Select port: COM')
#     # search for port
#     portUse = None
#     for port in portList:
#         if port.startswith('COM'+comNum):
#             portUse = 'COM' + comNum 
#     # check if port exists
#     if portUse==None : 
#         raise Exception('[!] COM port does not exist.')
# # create COM object 
# pod = POD_Basics(portUse)
# # verify communication link
# wrt = pod.WritePacket('PING')
# red = pod.ReadPODpacket()
# if(wrt == red):
#     print('Communication successful: ', red)
# else:
#     raise Exception('Communication Failiure: ', red)
# # delete pod object
# del pod


# DEMO 

# # initialization of commands 
# def InitCommands():
#     # Basic POD object
#     podB = POD_Basics(portUse)
#     print('Basic commands:\n', podB.GetDeviceCommands(),'\n')
#     del podB
#     # subclass of POD 
#     podR = POD_8206HR(portUse)
#     print('8206HR commands:\n',podR.GetDeviceCommands(),'\n')
#     del podR

# # command access
# def CommandAccess():
#     # create command dict object
#     cmds = POD_Commands()
#     print('POD_Commands initialization:\n',cmds.GetCommands(),'\n')
#     # adding commands to dict 
#     cmds.AddCommand(991,'TEST1',199,919,True)
#     cmds.AddCommand(992,'TEST2',299,929,True)
#     cmds.AddCommand(993,'TEST3',299,939,True)
#     print('POD_Commands (Add):\n',cmds.GetCommands(),'\n')
#     # removing command from dict 
#     cmds.RemoveCommand('TEST3')
#     print('POD_Commands (Rem):\n',cmds.GetCommands(),'\n')
#     # helpful functions 
#     print('TEST1 exists:\t',    cmds.DoesCommandExist('TEST1'))
#     print('TEST1 number:\t',    cmds.CommandNumberFromName('TEST1'))
#     print('TEST1 argument:\t',  cmds.ArgumentBytes('TEST1'))
#     print('TEST1 return:\t',    cmds.ReturnBytes('TEST1'))
#     print('TEST1 binary:\t',    cmds.IsCommandBinary('TEST1'))

# # standard read and write 
# def StandardReadWrite():
#     # create pod device object 
#     podR = POD_8206HR(portUse)
#     # Write and Read standard POD message with no packet 
#     w = podR.WritePacket('PING')
#     print('Write (PING):\t', w, podR.UnpackPODpacket(w), podR.TranslatePODpacket(w))
#     r = podR.ReadPODpacket()
#     print('Read (PING):\t', r, podR.UnpackPODpacket(r), podR.TranslatePODpacket(r))
#     print('\n')
#     # Write and Read standard POD message with a packet 
#     w = podR.WritePacket('GET LOWPASS', 0) # 0 = EEG1
#     print('Write (GET LOWPASS):\t', w, podR.UnpackPODpacket(w), podR.TranslatePODpacket(w))
#     r = podR.ReadPODpacket()
#     print('Read (GET LOWPASS):\t', r, podR.UnpackPODpacket(r), podR.TranslatePODpacket(r))
    
# # binary read
# def BinaryRead():
#     podR = POD_8206HR(portUse)
#     w = podR.WritePacket('STREAM', podR.IntToAsciiBytes(1,2)) # 1 = ON
#     r = podR.ReadPODpacket()
#     print('Read (BINARY4 DATA):\t', podR.TranslatePODpacket(r))
#     w = podR.WritePacket('STREAM', podR.IntToAsciiBytes(0,2)) # 1 = ON5
#     while(True):
#         r = podR.ReadPODpacket()
#         print('Read (BINARY4 DATA):\t', podR.TranslatePODpacket(r))

# # write and read (standard)
# def WriteRead():
#     # create pod device object 
#     podR = POD_8206HR(portUse)
#     # Write and Read standard POD message with no packet 
#     r = podR.WriteRead('PING')
#     print('Read (PING):\t', r, podR.UnpackPODpacket(r), podR.TranslatePODpacket(r))


# def Baudrate(br=9600) :
#     # create pod device object  
#     podR = POD_8206HR(portUse)
#     # set baudrate
#     b = podR.SetBaudrateOfDevice(br)
#     print('Was changing baudrate successful?:', b)


# run demos
# InitCommands()
# CommandAccess()
# StandardReadWrite()
# BinaryRead()
# WriteRead()
# Baudrate()

########## TESTING ##########################################################################################################

print('\n\n')

go = Setup_8206HR()
go.Run()

print('\n\n')

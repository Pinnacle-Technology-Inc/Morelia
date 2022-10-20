from Serial_InOut import COM_io
from BasicPodProtocol import POD_Basics

# # get port list 
# portList = COM_io.GetCOMportsList()

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
# com = COM_io(portUse)
# print('serial port in use:', com.GetPortName())

# # === test functions of COM_io

# # # read!
# # while True:
# #     # packet = com.ReadLine()
# #     # packet = com.Read(7)
# #     packet = com.ReadUntil(b'\r')
# #     print(packet)

# ping = COM_io.HexStrToByteArray('0230303032334403')
# stopat = COM_io.HexStrToByteArray('03')

# com.Write(ping)
# print('PING:', com.ReadUntil(stopat))

barr = bytearray([0x30,0x30,0x30,0x32])
check = POD_Basics.ChecksumBytes(barr)
# print(check)


stx = bytes.fromhex('02')
cmd = POD_Basics.ValueToBytes(2, 4) 
cs = POD_Basics.ChecksumBytes(barr)
etx = bytes.fromhex('03')
message = stx + cmd + cs + etx
print(message)

# next fix checksum to handle valueto bytes 

# test
msg = POD_Basics.ValueToBytes(2, 4) 
for b in msg:
    print(hex(b))
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

# myarr = '010203'
# bytearr = bytearray.fromhex(myarr)
# print(bytearr)

# b0 = 0x01
# b1 = 0x02
# b2 = 0x03
# blist = [b0,b1,b2]
# bytearr = bytearray(blist)
# print(bytearr)
# print(bytearr[0])
# print(bytearr[1])
# print(bytearr[2])

# blist = [0x30,0x30,0x30,0x36,0x30,0x01]
blist = [0x30,0x30,0x30,0x32]
barr = bytearray(blist)

sum = 0
for b in barr: 
    sum = sum + b
out = ~sum & 0xFF # get an unsigned 8 bit number range (0..255)
outstr = hex(out)

# get last to characters and make uppercase
c0 = outstr[len(outstr)-2].upper()
c1 = outstr[len(outstr)-1].upper()
c = [c0,c1]
print(c)

# get ascii code 
ascii0 = ord(c0)
ascii1 = ord(c1)
asc = [ascii0,ascii1]
print(ascii0)
print(ascii1)

print(hex(ascii0))
print(hex(ascii1))

arr = bytes(asc)
print(arr)
print(hex(arr[0]))
print(hex(arr[1]))

check = POD_Basics.ChecksumBytes(barr)
print(check)
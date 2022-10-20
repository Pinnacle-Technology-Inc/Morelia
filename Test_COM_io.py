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
# cmd = ???
cs = POD_Basics.ChecksumBytes(barr)
etx = bytes.fromhex('03')
# message = stx + cmd + cs + etx

# HERE VVV make into function 

def ValueToBytes(value, numBytes) : 
    # convert number into a hex string and remove the '0x' prefix
    num_hexStr = hex(value).replace('0x','')

    # split to access individual digits 
    num_hexStr_list = [x for x in num_hexStr]

    # convert each digit to an ascii code
    asciilist= []
    for character in num_hexStr_list: 
        # convert character to its ascii code and append to list  
        asciilist.append(ord(character))

    # get bytes for the ascii number 
    blist = []
    for ascii in asciilist :
        # convert ascii code to bytes and add to list 
        blist.append(bytes([ascii]))

    # if the number of bytes is smaller that requested, 
    # add zeros to beginning of the bytes to get desired size
    if (len(blist) < numBytes): 
        # ascii code for zero
        zero = bytes([ord('0')])
        # create list of zeros with size (NumberOfBytesWanted - LengthOfCurrentBytes))
        pre = [zero] * (numBytes - len(blist))
        # concatenate zeros list to remaining bytes
        post = pre + blist

    # if the number of bytes is greater that requested, 
    # keep the lowest bytes, remove the overflow 
    elif (len(blist) > numBytes) : 
        # get minimum index of bytes to keep
        min = len(blist) - numBytes
        # get indeces from min to end of list 
        post = blist[min:]

    # if the number of bytes is equal to that requested, 
    # keep the all the bytes, change nothing
    else : 
        post = blist

    # initialize message to first byte in 'post'
    msg = post[0]
    for i in range(numBytes-1) : 
        # concatenate next byte to end of the message 
        msg = msg + post[i+1]

    # return a byte message of a desired size 
    return(msg)

# numBytes = 4
# num = 100

# numhex = hex(num).replace('0x','')
# splitnumhex = [x for x in numhex]
# # print(splitnumhex)

# asciilist= []
# for character in splitnumhex: 
#     asciilist.append(ord(character))

# # print(asciilist)

# blist = []
# for ascii in asciilist :
#     blist.append(bytes([ascii]))

# # print(blist)

# if len(blist) < numBytes: 

#     zero = bytes([ord('0')])
#     preNum = numBytes - len(blist)
#     pre = [zero] * preNum
#     post = pre + blist
#     print(post)

# msg = post[0]
# for i in range(numBytes-1) : 
#     msg = msg + post[i+1]

# print(msg)

# make funtion ^^^

msg = ValueToBytes(100, 4) 

for b in msg:
    print(hex(b))
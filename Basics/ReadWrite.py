from struct import pack
from POD_io import COM_io

# get port list 
portList = COM_io.GetCOMportsList()

# check if the list is empty 
if not portList:
    raise Exception('[!] No COM ports in use. Exiting program.')

# use single option 
if( len(portList) == 1): 
    phrase = portList[0].split(' ')
    portUse = phrase[0]
    print('--> Using ', portUse)
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
        raise Exception('[!] COM port does not exist. Exiting program.')

# create COM object 
com = COM_io(portUse)

# read!
while True:
    packet = com.ReadLineWhenReady()
    print(packet)
from Morelia.Devices.BasicPodProtocol import Pod
import os

devices = os.listdir('/dev')
usb_devices = []

for x in devices:
    if 'ttyUSB' in x:
        usb_devices.append('/dev/' + x)

pod_devices = []

for x in usb_devices:
  pod_test = Pod(x)
  if (pod_test.test_connection()):
    device_type = pod_test.write_read('TYPE').payload[0]
    device_id = pod_test.write_read('ID').payload[0]
    pod_devices.append({'PORT':x, 'TYPE':device_type, 'ID':device_id})

for x in pod_devices:
    print ('Pod Device found on ' + x['PORT'] + ' with type ' + str(x['TYPE']) + ' and ID ' + str(x['ID']))
    

# queue_server.py
import time
import re
from multiprocessing.managers import BaseManager
from multiprocessing import Queue
import sys

class ControlPacketManager(BaseManager): pass

def get_port_for_device(dev_path: str) -> int:
    base_port = 50000
    if "ttyUSB" in dev_path:
        suffix = re.findall(r'ttyUSB(\d+)', dev_path)
        return base_port + int(suffix[0])
    elif "COM" in dev_path:
        suffix = re.findall(r'COM(\d+)', dev_path)
        return base_port + int(suffix[0])
    return base_port

# script to run in subprocess for port 
if __name__ == '__main__':
    # obtain the port from passed in process arg
    port = sys.argv[1]

    # create new Queues for the write/read queue
    write_queue = Queue()
    read_queue = Queue()

    # register the Base Managers for each queue, and set the callable to the queues above
    ControlPacketManager.register(f'get_write_queue_{port}', callable=lambda: write_queue)
    ControlPacketManager.register(f'get_read_queue_{port}', callable=lambda: read_queue)

    # obtain the local port for the device
    local_port = get_port_for_device(port)
    manager = ControlPacketManager(address=('localhost', local_port), authkey=b'secret')

    # start the server
    print(f"[queue_server] Starting queue server for port {port} on localhost:{local_port}")
    server = manager.get_server()
    server.serve_forever()


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

if __name__ == '__main__':
    port = sys.argv[1]
    write_queue = Queue()
    read_queue = Queue()

    ControlPacketManager.register(f'get_write_queue_{port}', callable=lambda: write_queue)
    ControlPacketManager.register(f'get_read_queue_{port}', callable=lambda: read_queue)

    local_port = get_port_for_device(port)
    manager = ControlPacketManager(address=('localhost', local_port), authkey=b'secret')

    print(f"[queue_server] Starting queue server for port {port} on localhost:{local_port}")
    server = manager.get_server()
    server.serve_forever()


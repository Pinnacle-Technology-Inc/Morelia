# queue_server.py
import time
import re
from multiprocessing.managers import BaseManager
from multiprocessing import Queue
import sys

class ControlPacketManager(BaseManager): pass

def get_port_for_device(dev_path: str) -> int:
    '''
    returns the local host port for the device, using IANA dynamic port range (51000-65535).
    For COM/ttyUSB the suffix digit is used; for D2XX (serial string) a stable
    hash of the string is used so each device gets a unique port and queue names match.
    Must match queue_manager.get_port_for_device() exactly.
    '''
    # Use IANA dynamic port range (49152-65535) to avoid Windows reserved ports
    # Start from 51000 to leave room and avoid conflicts
    base_port = 51000
    dev_path = str(dev_path)
    
    #for linux machines (WSL)
    if "ttyUSB" in dev_path:
        suffix = re.findall(r'ttyUSB(\d+)', dev_path)
        if suffix:
            return base_port + int(suffix[0])
    
    #for windows machines
    elif "COM" in dev_path:
        suffix = re.findall(r'COM(\d+)', dev_path)
        if suffix:
            return base_port + int(suffix[0])
    
    # D2XX and other: use stable hash of string so each device/serial gets unique port
    # Use modulo 14536 to stay within 51000-65535 range
    # Must match queue_manager.get_port_for_device() exactly
    # Handle empty strings specially to avoid conflicts (empty string hashes to 0)
    if not dev_path or not dev_path.strip():
        # Empty string would hash to port 51000, causing conflicts
        # Use a hash of a marker string instead
        dev_path = "D2XX_EMPTY_SERIAL"
    return base_port + (sum(ord(c) for c in dev_path) % 14536)

# script to run in subprocess for port
if __name__ == '__main__':
    print(f"[queue_server] argv={sys.argv}", flush=True)
    try:
        if len(sys.argv) < 2:
            print("[queue_server] usage: queue_server.py <port_or_serial>", flush=True)
            sys.exit(1)
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
        print(f"[queue_server] Starting queue server for port {port} on localhost:{local_port}", flush=True)
        server = manager.get_server()
        server.serve_forever()
    except Exception as e:
        print(f"[queue_server] ERROR: {e}", flush=True)
        raise


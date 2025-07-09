"""Class to initialize a Queue for acceptance of multiple ControlPacket objects from the user (in the case that multiple scripts are being run)"""

__author__      = 'Andrew Huang'
__maintainer__  = 'Andrew Huang'
__credits__     = ['Andrew Huang', 'Josselyn Bui', 'James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2023, Andrew Huang'
__email__       = 'sales@pinnaclet.com'

#environment imports

from multiprocessing.managers import BaseManager
from multiprocessing import Queue
import multiprocessing as mp
import socket
import time


class ControlPacketManager(BaseManager): 
    pass

class PacketManager:

    def __init__(self):
        """
        Runs when the PacketManager is instantiated within the PortIO object belonging to the Acquisition device.
        """
        self._queue = None
        self._queue_initialized = False
        self._queue_registered = False

    def port_in_use(self, host, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex((host, port)) == 0

    def initialize_control_queue(self):
        """
        Initializes multiprocessing Queue for use between processes. 
        """
        if self.port_in_use('localhost', 50000):
            raise RuntimeError("Queue manager is already running on the port. Use register_control_queue instead")
        
        worker = mp.Process(target=self.create_control_queue_process)
        worker.daemon = True
        worker.start()

        time.sleep(0.5)

        self.register_control_queue()
        self._queue_initialized = True

    def create_control_queue_process(self):

        shared_queue = Queue()
        ControlPacketManager.register('get_queue', callable=lambda: shared_queue)

        manager = ControlPacketManager(address=('localhost', 50000), authkey=b'secret')
        server = manager.get_server()
        server.serve_forever()

    def register_control_queue(self, retries=5):
        """
        Registers the initialized Queue for an acquisition device.
        """
        ControlPacketManager.register('get_queue')
        
        manager = ControlPacketManager(address=('localhost', 50000), authkey=b'secret')
        
        manager.connect()

        #connected = False
        #for attempt in range(retries):
        #    try:
        #        manager.connect()
        #        connected = True
        #        break
        #    except ConnectionRefusedError:
        #        if attempt == retries - 1:
        #            raise
        #        time.sleep(0.1 * (2 ** attempt))
        #if not connected: 
        #    raise RuntimeError("Failed to connect to the manager")
        queue = manager.get_queue()

        self._queue = queue
        self._queue_registered = True

    def obtain_queue(self):
        return self._queue

    def queue_initialized(self):
        return self._queue_initialized

    def queue_registered(self):
        return self._queue_registered
    

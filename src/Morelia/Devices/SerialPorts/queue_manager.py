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
        Initializes a new process to run the Queue server/socket.
        """
        if self.port_in_use('localhost', 50000):
            raise RuntimeError("Queue manager is already running on the port. Use register_control_queue instead")
        
        # creates a new process
        worker = mp.Process(target=self.create_control_queue_process)

        # destroy the process when the parent process exits
        worker.daemon = True

        # begin the process
        worker.start()

        # wait for half a second for server to begin
        time.sleep(0.5)

        # register the queue in the parent process
        self.register_control_queue()
        self._queue_initialized = True

    def create_control_queue_process(self):
        """
        Creates a new queue and starts the server to run until the parent process dies. 
        """
        
        # creates a multiprocessing queue object
        shared_queue = Queue()

        # register a function in the BaseManager that returns the shared queue
        ControlPacketManager.register('get_queue', callable=lambda: shared_queue)

        # create the ControlPacketManager on the localhost port 500000 and set an authentication key
        manager = ControlPacketManager(address=('localhost', 50000), authkey=b'secret')


        # gets the server from the manager
        server = manager.get_server()

        # runs the server forever (blocking)
        server.serve_forever()

    def register_control_queue(self):
        """
        Registers the initialized Queue for an acquisition device.
        """
        ControlPacketManager.register('get_queue')
        
        manager = ControlPacketManager(address=('localhost', 50000), authkey=b'secret')
        
        manager.connect()

        queue = manager.get_queue()

        self._queue = queue
        self._queue_registered = True

    def obtain_queue(self):
        return self._queue

    def queue_initialized(self):
        return self._queue_initialized

    def queue_registered(self):
        return self._queue_registered
    

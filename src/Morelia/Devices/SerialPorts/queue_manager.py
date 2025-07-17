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
        self._write_queue = None
        self._read_queue = None
        self._queues_initialized = False
        self._queues_registered = False

    def port_in_use(self, host, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex((host, port)) == 0

    def initialize_control_queue(self):
        """
        Initializes a new process to run the Queue server/socket.
        """
        port_num = 50000
        while self.port_in_use('localhost', port_num):
            port_num += 1
        
        # creates a new process
        worker = mp.Process(target=self.create_control_queue_process, args=(port_num,))

        # destroy the process when the parent process exits
        worker.daemon = True

        # begin the process
        worker.start()

        # wait for half a second for server to begin
        time.sleep(0.1)

        # register the queue in the parent process
        self.register_control_queue()
        self._queues_initialized = True

    def create_control_queue_process(self, port_num):
        """
        Creates a new queue and starts the server to run until the parent process dies. 
        """
        
        # creates a multiprocessing queue object
        write_queue = Queue()
        read_queue = Queue()

        # register a function in the BaseManager that returns the shared queue
        ControlPacketManager.register('get_write_queue', callable=lambda: write_queue)
        ControlPacketManager.register('get_read_queue', callable=lambda: read_queue)

        # create the ControlPacketManager on the localhost port 50000 and set an authentication key
        manager = ControlPacketManager(address=('localhost', port_num), authkey=b'secret')

        # gets the server from the manager
        server = manager.get_server()

        # runs the server forever (blocking)
        server.serve_forever()

    def register_control_queue(self):
        """
        Registers the initialized Queue for an acquisition device.
        """
        ControlPacketManager.register('get_write_queue')
        ControlPacketManager.register('get_read_queue')
        
        #this will need to be changed for a different port depending on physical device
        manager = ControlPacketManager(address=('localhost', 50000), authkey=b'secret')
        
        manager.connect()

        write_queue = manager.get_write_queue()
        read_queue = manager.get_read_queue()

        self._write_queue = write_queue
        self._read_queue = read_queue
        self._queues_registered = True

    def obtain_write_queue(self):
        return self._write_queue
 
    def obtain_read_queue(self):
        return self._read_queue
 
    def queues_initialized(self):
        return self._queues_initialized

    def queues_registered(self):
        return self._queues_registered
        

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
import platform, subprocess, os
import socket
import time
import re

class ControlPacketManager(BaseManager): 
    pass

class PacketManager:

    def __init__(self, port):
        """
        Runs when the PacketManager is instantiated within the PortIO object belonging to the Acquisition device.
        """
        self.port = port
        self._queue = None
        self._write_queue = None
        self._read_queue = None

    def port_in_use(self, host, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex((host, port)) == 0

    def initialize_control_queue(self):
        """
        Initializes a new subprocess to run the Queue server/socket.
        """
        # obtain the system from the platform module
        system = platform.system()
        
        # find this current directory, and the script to run the server 
        this_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(this_dir, "queue_server.py")

        # if the system is not Windows,
        if system != "Windows":
            # open a subprocess of the script using python3 
            subprocess.Popen(
                ['python3', script_path, self.port],
                preexec_fn=os.setsid, 
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True
            )
        # if the system is Windows, 
        else:
            # open a subprocess of the script using python
            subprocess.Popen(
                ['python', script_path, self.port],
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True
            )

        # wait for 0.1 of a second for server to begin
        time.sleep(0.1)

        # register the queue in the parent process
        self.register_control_queue(self.port)

    def create_control_queue_process(self, port):
        """
        Creates a new queue and starts the server to run until the parent process dies. 
        **This function may be depricated and should be removed
        """
        
        # creates a multiprocessing queue object
        write_queue = Queue()
        read_queue = Queue()

        # register functions in the BaseManager that return the shared queues
        ControlPacketManager.register(f'get_write_queue_{port}', callable=lambda: write_queue)
        ControlPacketManager.register(f'get_read_queue_{port}', callable=lambda: read_queue)

        # obtain the local port based on the number of the port passed in
        local_port = self.get_port_for_device(port)

        # create the ControlPacketManager on the localhost port and set an authentication key
        manager = ControlPacketManager(address=('localhost', local_port), authkey=b'secret')

        # gets the server from the manager
        server = manager.get_server()

        # runs the server forever (blocking)
        server.serve_forever()

    def register_control_queue(self, port):
        """
        Registers the initialized Queue for an acquisition device.
        """
        # registers both functions that return the shared queues
        ControlPacketManager.register(f'get_write_queue_{port}')
        ControlPacketManager.register(f'get_read_queue_{port}')

        # obtain the local port based on the number of the port passed in
        local_port = self.get_port_for_device(port)

        #this will need to be changed for a different port depending on physical device
        manager = ControlPacketManager(address=('localhost', local_port), authkey=b'secret')
        
        # tries to connect to the manager 
        manager.connect()
        
        # obtain the write queue and read queue from the port name
        write_queue = getattr(manager, f'get_write_queue_{port}')()
        read_queue = getattr(manager, f'get_read_queue_{port}')()

        # set class variables
        self._write_queue = write_queue
        self._read_queue = read_queue
        self._queues_registered = True
    
    def get_port_for_device(self, dev_path: str) -> int:
        '''
        returns the local host port for the device, based on a base port of 50000
        '''
        base_port = 50000

        #for linux machines (WSL)
        if "ttyUSB" in dev_path:
            suffix = re.findall(r'ttyUSB(\d+)', dev_path)
            return base_port + int(suffix[0])

        #for windows machines 
        elif "COM" in dev_path:
            suffix = re.findall(r'COM(\d+)', dev_path)
            return base_port + int(suffix[0])

        return base_port

    # functions to obtain values of the queues
    def obtain_write_queue(self):
        return self._write_queue
 
    def obtain_read_queue(self):
        return self._read_queue

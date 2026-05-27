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
        self._server_process = None  # Store subprocess handle for cleanup
        self._server_started_by_us = False  # Track if we started the server

    def port_in_use(self, host, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex((host, port)) == 0

    def initialize_control_queue(self):
        """
        Initializes a new subprocess to run the Queue server/socket.
        """
        # Check if server is already running for this port (e.g. from previous run)
        local_port = self.get_port_for_device(self.port)
        if not self.port_in_use('localhost', local_port):
            # Port is free - start a new server subprocess
            # obtain the system from the platform module
            system = platform.system()
            
            # find this current directory, and the script to run the server 
            this_dir = os.path.dirname(os.path.abspath(__file__))
            script_path = os.path.join(this_dir, "queue_server.py")

            # if the system is not Windows,
            if system != "Windows":
                # open a subprocess of the script using python3 (stderr visible if server fails to start)
                # Store the process handle so we can terminate it later
                self._server_process = subprocess.Popen(
                    ['python3', script_path, self.port],
                    preexec_fn=os.setsid, 
                    stdout=subprocess.DEVNULL,
                    close_fds=True
                )
            # if the system is Windows, 
            else:
                # open a subprocess of the script using python (stderr visible if server fails to start)
                # Store the process handle so we can terminate it later
                self._server_process = subprocess.Popen(
                    ['python', script_path, self.port],
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                    stdout=subprocess.DEVNULL,
                    close_fds=True
                )
            
            self._server_started_by_us = True

            # wait for server subprocess to bind (longer on Windows / cold start)
            time.sleep(0.3)
        # else: port is already in use, assume server is running and skip starting new one

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

        # Retry connect: subprocess may need longer than 0.1s to bind (e.g. Windows, different serial)
        max_attempts = 15
        for attempt in range(max_attempts):
            try:
                manager.connect()
                break
            except (ConnectionRefusedError, OSError) as e:
                if attempt == max_attempts - 1:
                    raise
                time.sleep(0.2)

        # obtain the write queue and read queue from the port name
        write_queue = getattr(manager, f'get_write_queue_{port}')()
        read_queue = getattr(manager, f'get_read_queue_{port}')()

        # set class variables
        self._write_queue = write_queue
        self._read_queue = read_queue
        self._queues_registered = True
    
    def get_port_for_device(self, dev_path: str) -> int:
        '''
        returns the local host port for the device, using IANA dynamic port range (51000-65535).
        For COM/ttyUSB the suffix digit is used; for D2XX (serial string) a stable
        hash of the string is used so each device gets a unique port and queue names match.
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
        # Handle empty strings specially to avoid conflicts (empty string hashes to 0)
        if not dev_path or not dev_path.strip():
            # Empty string would hash to port 51000, causing conflicts
            # Use a hash of a marker string instead
            dev_path = "D2XX_EMPTY_SERIAL"
        return base_port + (sum(ord(c) for c in dev_path) % 14536)

    def cleanup(self):
        """
        Clean up resources, including terminating the queue server subprocess if we started it.
        """
        if self._server_process is not None and self._server_started_by_us:
            try:
                system = platform.system()
                if system == "Windows":
                    # On Windows, terminate the process group
                    try:
                        self._server_process.terminate()
                        # Give it a moment to terminate gracefully
                        try:
                            self._server_process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            # If it doesn't terminate, force kill
                            self._server_process.kill()
                            self._server_process.wait()
                    except (ProcessLookupError, ValueError):
                        # Process already terminated
                        pass
                else:
                    # On Linux/Mac, kill the process group (since we used os.setsid)
                    try:
                        # Get the process group ID (negative PID kills the group)
                        pgid = os.getpgid(self._server_process.pid)
                        os.killpg(pgid, 15)  # SIGTERM
                        # Give it a moment to terminate gracefully
                        try:
                            self._server_process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            # If it doesn't terminate, force kill
                            os.killpg(pgid, 9)  # SIGKILL
                            self._server_process.wait()
                    except (ProcessLookupError, OSError, ValueError):
                        # Process already terminated or group doesn't exist
                        pass
            except Exception:
                # Ignore errors during cleanup - process may already be gone
                pass
            finally:
                self._server_process = None
                self._server_started_by_us = False

    def __del__(self):
        """Cleanup when PacketManager is destroyed."""
        self.cleanup()

    # functions to obtain values of the queues
    def obtain_write_queue(self):
        return self._write_queue
 
    def obtain_read_queue(self):
        return self._read_queue

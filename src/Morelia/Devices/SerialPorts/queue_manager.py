"""Class to initialize a Queue for acceptance of multiple ControlPacket objects from the user (in the case that multiple scripts are being run)"""

__author__      = 'Andrew Huang'
__maintainer__  = 'Andrew Huang'
__credits__     = ['Andrew Huang', 'Josselyn Bui', 'James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2023, Andrew Huang'
__email__       = 'sales@pinnaclet.com'

#environment imports

from multiprocessing.managers import BaseManager
from multiprocessing import Queue, Lock

class ControlPacketManager(BaseManager): 
    pass

class PacketManager:

    def __init__(self):
        """
        Runs when the PacketManager is instantiated within the PortIO object belonging to the Acquisition device.
        """
        self._queue = None
        #self._lock = None
        self._queue_initialized = False
        self._queue_registered = False

    def initialize_control_queue(self):
        """
        Initializes multiprocessing Queue for use between processes. 
        """
        shared_queue = Queue()
        shared_lock = Lock()
        ControlPacketManager.register('get_queue', callable=lambda: shared_queue)
        ControlPacketManager.register('get_lock', callable=lambda: shared_lock)

        manager = ControlPacketManager(address=('', 50000), authkey=b'secret')
        manager.start()
        queue = manager.get_queue()
        lock = manager.get_lock()
        self._queue = queue
        self._lock = lock
        self._queue_initialized = True

    def register_control_queue(self):
        """
        Registers the initialized Queue for an acquisition device.
        """
        ControlPacketManager.register('get_queue')
        ControlPacketManager.register('get_lock')

        manager = ControlPacketManager(address=('', 50000), authkey=b'secret')
        manager.connect()

        queue = manager.get_queue()
        lock = manager.get_lock()

        self._queue = queue
        self._lock = lock
        self._queue_registered = True

    def obtain_queue(self):
        return self._queue

    def obtain_lock(self):
        return self._lock

    def queue_initialized(self):
        return self._queue_initialized

    def queue_registered(self):
        return self._queue_registered

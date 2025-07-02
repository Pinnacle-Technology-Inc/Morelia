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

class ControlPacketQueue(BaseManager): 
    pass

class PacketManager:

    def __init__(self):
        """
        Runs when the PacketManager is instantiated within the PortIO object belonging to the Acquisition device.
        """
        self._queue = None
        self._queue_initialized = False
        self._queue_registered = False

    def initialize_control_queue(self):
        """
        Initializes multiprocessing Queue for use between processes. 
        """
        q = Queue()
        ControlPacketQueue.register('get_queue', callable=lambda: q)
        manager = ControlPacketQueue(address=('', 50000), authkey=b'secret')
        manager.start()
        q = manager.get_queue()
        self._queue = q
        self._queue_initialized = True

    def register_control_queue(self):
        """
        Registers the initialized Queue for an acquisition device.
        """
        ControlPacketQueue.register('get_queue')
        manager = ControlPacketQueue(address=('', 50000), authkey=b'secret')
        manager.connect()
        q = manager.get_queue()
        self._queue = q
        self._queue_registered = True

    def obtain_queue(self):
        return self._queue

    def queue_initialized(self):
        return self._queue_initialized

    def queue_registered(self):
        return self._queue_registered

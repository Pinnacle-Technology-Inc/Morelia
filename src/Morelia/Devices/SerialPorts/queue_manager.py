from multiprocessing.managers import BaseManager
from queue import Queue


class ControlPacketQueue(BaseManager): 
    pass

class PacketManager:

    def __init__(self):
        self._queue = None
        self._queue_initialized = False
        self._queue_registered = False

    def initialize_control_queue(self):
        q = Queue()
        ControlPacketQueue.register('get_queue', callable=lambda: q)
        manager = ControlPacketQueue(address=('', 50000), authkey=b'secret')
        manager.start()
        q = manager.get_queue()
        self._queue = q
        self._queue_initialized = True

    def register_control_queue(self):
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

from queue import Queue

class MockQueueManager:
    def __init__(self):
        self._read_queue = Queue()
        self._write_queue = Queue()

    def obtain_read_queue(self):
        return self._read_queue

    def obtain_write_queue(self):
        return self._write_queue
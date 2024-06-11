from multiprocessing import Event
from multiprocessing.connection import Connection
import multiprocessing as mp

def drain(pipe: Connection, end_stream_event: Event) -> None:
    c = 0
    while not end_stream_event.is_set():
        pipe.recv()
        c += 1

    print(c)

class Drain:

    def __init__(self, conn, event) :
        self._connection = conn
        self._event = event
        self.c = 0

    def Read(self) -> mp.Process:
        proc: mp.Process = mp.Process(target=self._Read)
        proc.start()
        return proc

    def _Read(self):

        while not self._event.is_set():
            thing = self._connection.recv()
            self.c += 1
        print(self.c)

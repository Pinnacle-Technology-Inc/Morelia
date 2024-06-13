from multiprocessing import Event
from multiprocessing.connection import Connection
import multiprocessing as mp
import pandas as pd
import os
import json

import influxdb_client, os, time
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from PodApi.Stream.PodHandler import Drain8206HR, Drain8274D, Drain8401HR 
from PodApi.Devices import Pod8206HR, Pod8401HR, Pod8274D

def volts_to_microvolts(voltage: float|int) -> float:

        # round to 6 decimal places... add 0.0 to prevent negative zeros when rounding
        return ( round(voltage * 1E6, 12 ) + 0.0 )

def drain_to_influx(pipe: Connection, end_stream_event: Event, pod: Pod8206HR | Pod8274D | Pod8401HR):
    #token = os.environ.get('INFLUXDB_TOKEN')
    
    with open('auth.json') as f:
        token = json.load(f)['INFLUX_API_TOKEN']

    org = 'pinnacle'
    url = 'http://localhost:8086'
    bucket = 'pinnacle'
    
    if isinstance(pod,Pod8206HR):
        dev_handler: Drain8206HR = Drain8206HR()
    elif isinstance (pod,Pod8401HR):
        dev_handler: Drain8401HR = Drain8401HR()
    elif isinstance(pod,Pod8274D):
        dev_handler: Drain8274D = Drain8274D()
    
    with influxdb_client.InfluxDBClient(url=url, token=token, org=org) as write_client:
        with write_client.write_api() as write_api:
            while not end_stream_event.is_set():

                timestamps, raw_data = pipe.recv()
                structured_data: pd.DataFrame = dev_handler.DropToDf(timestamps,raw_data).set_index('Time')

                for time, data in structured_data.iterrows():
                    for channel, data_point in data.items():
                        point = Point('realish_test3').time(time).tag('channel', channel).field('value', data_point)
                        write_api.write(bucket=bucket, org="pinnacle", record=point)

def drain(pipe: Connection, end_stream_event: Event) -> None:
    c = 0
    while not end_stream_event.is_set():
        print(c)
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

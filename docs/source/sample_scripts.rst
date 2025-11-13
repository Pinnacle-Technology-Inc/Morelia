#####################################
Sample Scripts For Streaming 🧠
#####################################

Examples of what a script might look like for each pod device that Morelia currently supports. 

.. important::

   If you are running Morelia in Windows, you'll need to wrap all of your code in the block below: 

.. code-block:: python

   if __name__ == "__main__":
      '''
      All code should be placed here, besides imports
      '''

=================
8206HR Examples 
=================

**Streaming a single 8206HR device to an EDF file infinitely:**
      
.. code-block:: python 
  
  # import classes from submodules 
  from Morelia.Devices import Pod8206HR
  from Morelia.Stream.sink import EDFSink
  from Morelia.Stream.data_flow import DataFlow

  # create a new 8206HR pod device from the Linux port ttyUSB0 
  pod_1 = Pod8206HR('/dev/ttyUSB0', 10)

  # create a new edf sink object, using the dump_1.edf file from the same directory
  edf_sink_1 = EDFSink('dump_1.edf', pod_1)

  # create a list of tuples for the pod/sink mappings 
  mapping = [(pod_1, [edf_sink_1])]

  # create a new DataFlow object using the previous mapping 
  flowgraph = DataFlow(mapping)

  # set flag to false 
  flag = False

  # use 'with' statement to begin streaming 
  with flowgraph:

    # stream infinitely
    while True:
      if flag:
        break

**Streaming a single 8206HR device to an Influx database for 30 seconds:**

.. code-block:: python

  # import classes from submodules 
  from Morelia.Devices import Pod8206HR
  from Morelia.Stream.sink import InfluxSink
  from Morelia.Stream.data_flow import DataFlow

  # create a new 8206HR pod device from the Linux port ttyUSB0 
  pod_1 = Pod8206HR('/dev/ttyUSB0', 10)

  # create a new influx sink object, using user-defined values 
  # for a container outside of the terraform one provided
  # reminder: bucket in influx is like a database, and measurement is like a table.
  influx_sink_1 = InfluxSink(pod=pod_1, url='http://localhost:8086', api_token='supersecret', org='pinnacle', bucket='influx_dump', measurement='experiment1')

  # create a list of tuples for the pod/sink mappings 
  mapping = [(pod_1, [influx_sink_1])]

  # create a new DataFlow object using the previous mapping 
  flowgraph = DataFlow(mapping)
  
  # stream from the flowgraph for 30 seconds
  flowgraph.collect_for_seconds(30)

**Streaming multiple 8206HR devices to an Influx database and EDF files infinitely:**

.. code-block:: python

  # import classes from submodules 
  from Morelia.Devices import Pod8206HR
  from Morelia.Stream.sink import InfluxSink, EDFSink
  from Morelia.Stream.data_flow import DataFlow

  # create 3 new 8206HR pod devices from the Linux ports ttyUSB0, ttyUSB1, and ttyUSB2
  pod_1 = Pod8206HR('/dev/ttyUSB0', 10)
  pod_2 = Pod8206HR('/dev/ttyUSB1', 10)
  pod_3 = Pod8206HR('/dev/ttyUSB2', 10)

  # create 3 new edf sink objects, using the 
  # dump_1.edf, dump_2.edf, and dump_3.edf files from the same directory
  edf_sink_1 = EDFSink('dump_1.edf', pod_1)
  edf_sink_2 = EDFSink('dump_2.edf', pod_2)
  edf_sink_3 = EDFSink('dump_3.edf', pod_3)

  # create 3 new influx sink objects, using the default values in the influx sink class 
  influx_sink_1 = InfluxSink(pod_1)
  influx_sink_2 = InfluxSink(pod_2)
  influx_sink_3 = InfluxSink(pod_3)

  # create a list of tuples for the pod/sink mappings 
  mapping = [(pod_1, [edf_sink_1, influx_sink_1]), 
             (pod_2, [edf_sink_2, influx_sink_2]), 
             (pod_3, [edf_sink_3, influx_sink_3])]

  # create a new DataFlow object using the previous mapping 
  flowgraph = DataFlow(mapping)

  # set flag to false
  flag = False

  # begin collection from flowgraph
  flowgraph.collect()

  # stream infinitely
  while True:
    if flag:
      break

  # stop streaming
  flowgraph.stop_collection()

**Sending Packets to a 8206HR Device**

.. code-block:: python
  
  # import classes from submodules 
  from Morelia.Devices import Pod8206HR
  import time

  # create 4 new 8206HR pod devices from the Linux ports ttyUSB0, ttyUSB1, and ttyUSB2
  pod_1 = Pod8206HR('/dev/ttyUSB0', 10)
  pod_2 = Pod8206HR('/dev/ttyUSB1', 10)
  pod_3 = Pod8206HR('/dev/ttyUSB2', 10)
  pod_4 = Pod8206HR('/dev/ttyUSB3', 10)

  # add pods to a list, with the names of each pod
  pod_list = [("pod_1", pod_1), 
              ("pod_2", pod_2), 
              ("pod_3", pod_3), 
              ("pod_4", pod_4)]

  # update the sample rates of all of the pod devices to 500 
  for name, pod in pod_list:
    pod.sample_rate = 500
    sample_rate = pod.write_read('GET SAMPLE RATE').payload[0]
    print(f"Sample rate value of {name} after update to 500: {sample_rate}")

  # update the sample rates of all of the pod devices to 2000 (maximum)
  for name, pod in pod_list:
    pod.sample_rate = 2000
    sample_rate = pod.write_read('GET SAMPLE RATE').payload[0]
    print(f"Sample rate value of {name} after update to 2000: {sample_rate}")

  # update the TTL of all of the pod devices to 0 
  for name, pod in pod_list:
    pod.write_packet('SET TTL OUT', (0,0))
    # add a small sleep so that the response to the write packet 
    # above does not interfere with the write_read
    time.sleep(0.1)
    ttl_val = pod.write_read('GET TTL IN', 0).payload
    print(f"TTL value of {name} after update to 0: {ttl_val}")

  # update the TTL of all of the pod devices to 1
  for name, pod in pod_list:
    pod_1.write_packet('SET TTL OUT', (0,1))
    # add a small sleep so that the response to the write packet 
    # above does not interfere with the write_read 
    time.sleep(0.1)
    ttl_val = pod.write_read('GET TTL IN', 0)
    print(f"TTL value of {name} after update to 1: {ttl_val}")

=================
8401HR Examples 
=================

**Streaming a single 8401HR device to an EDF file infinitely:**

.. code-block:: python

  # import classes from submodules 
  from Morelia.Devices import Pod8401HR, Preamp
  from Morelia.Stream.sink import EDFSink
  from Morelia.Stream.data_flow import DataFlow
  from Morelia.packet import PrimaryChannelMode, SecondaryChannelMode

  # set preamp gain and ss gain for all channels 
  preamp_gain = (10,10,10,10)
  ss_gain = (5,5,5,5)

  # set the primary channel modes to EEG/EMG or BIOSENSOR
  primary_channel_modes = (PrimaryChannelMode.EEG_EMG, PrimaryChannelMode.EEG_EMG, PrimaryChannelMode.EEG_EMG, PrimaryChannelMode.EEG_EMG)

  # set the secondary channel modes to DIGITAL or ANALOG 
  secondary_channel_modes =  (SecondaryChannelMode.DIGITAL, SecondaryChannelMode.DIGITAL, SecondaryChannelMode.DIGITAL, SecondaryChannelMode.DIGITAL, SecondaryChannelMode.DIGITAL, SecondaryChannelMode.DIGITAL)

  # create a new 8401HR pod device from the Linux port ttyUSB0, and with the initialized values above
  pod_1 = Pod8401HR('/dev/ttyUSB0', Preamp.Preamp8406_SE4, primary_channel_modes, secondary_channel_modes, ss_gain, preamp_gain) 

  # create a new edf sink object, using the dump_1.edf file from the same directory
  edf_sink_1 = EDFSink('dump_1.edf', pod_1)

  # create a list of tuples for the pod/sink mappings 
  mapping = [(pod_1, [edf_sink_1])]

  # create a new DataFlow object using the previous mapping 
  flowgraph = DataFlow(mapping)

  # set flag to false 
  flag = False

  # use 'with' statement to begin streaming 
  with flowgraph:

    # stream infinitely
    while True:
      if flag:
        break

**Streaming a single 8401HR device to an Influx database for 30 seconds:**

.. code-block:: python

  # import classes from submodules 
  from Morelia.Devices import Pod8401HR, Preamp
  from Morelia.Stream.sink import InfluxSink 
  from Morelia.Stream.data_flow import DataFlow
  from Morelia.packet import PrimaryChannelMode, SecondaryChannelMode

  # set preamp gain and ss gain for all channels 
  preamp_gain = (10,10,10,10)
  ss_gain = (5,5,5,5)

  # set the primary channel modes to EEG/EMG or BIOSENSOR
  primary_channel_modes = (PrimaryChannelMode.EEG_EMG, PrimaryChannelMode.EEG_EMG, PrimaryChannelMode.EEG_EMG, PrimaryChannelMode.EEG_EMG)

  # set the secondary channel modes to DIGITAL or ANALOG 
  secondary_channel_modes =  (SecondaryChannelMode.DIGITAL, SecondaryChannelMode.DIGITAL, SecondaryChannelMode.DIGITAL, SecondaryChannelMode.DIGITAL, SecondaryChannelMode.DIGITAL, SecondaryChannelMode.DIGITAL)

  # create a new 8401HR pod device from the Linux port ttyUSB0, and with the initialized values above
  pod_1 = Pod8401HR('/dev/ttyUSB0', Preamp.Preamp8406_SE4, primary_channel_modes, secondary_channel_modes, ss_gain, preamp_gain) 

  # create a new influx sink object, using user-defined values 
  # for a container outside of the terraform one provided
  # reminder: bucket in influx is like a database, and measurement is like a table.
  influx_sink_1 = InfluxSink(pod=pod_1, url='http://localhost:8086', api_token='supersecret', org='pinnacle', bucket='influx_dump', measurement='experiment1')

  # create a list of tuples for the pod/sink mappings 
  mapping = [(pod_1, [influx_sink_1])]

  # create a new DataFlow object using the previous mapping 
  flowgraph = DataFlow(mapping)
  
  # stream from the flowgraph for 30 seconds
  flowgraph.collect_for_seconds(30)

**Streaming multiple 8401HR devices to an Influx database and EDF files infinitely:**

.. code-block:: python

  # import classes from submodules 
  from Morelia.Devices import Pod8401HR, Preamp
  from Morelia.Stream.sink import InfluxSink, EDFSink
  from Morelia.Stream.data_flow import DataFlow
  from Morelia.packet import PrimaryChannelMode, SecondaryChannelMode

  # set preamp gain and ss gain for all channels 
  preamp_gain = (10,10,10,10)
  ss_gain = (5,5,5,5)

  # set the primary channel modes to EEG/EMG or BIOSENSOR
  primary_channel_modes = (PrimaryChannelMode.EEG_EMG, PrimaryChannelMode.EEG_EMG, PrimaryChannelMode.EEG_EMG, PrimaryChannelMode.EEG_EMG)

  # set the secondary channel modes to DIGITAL or ANALOG 
  secondary_channel_modes =  (SecondaryChannelMode.DIGITAL, SecondaryChannelMode.DIGITAL, SecondaryChannelMode.DIGITAL, SecondaryChannelMode.DIGITAL, SecondaryChannelMode.DIGITAL, SecondaryChannelMode.DIGITAL)

  # create 3 new 8401HR pod devices from the Linux ports ttyUSB0, ttyUSB1, and ttyUSB2
  # with the initialized values above
  pod_1 = Pod8401HR('/dev/ttyUSB0', Preamp.Preamp8406_SE4, primary_channel_modes, secondary_channel_modes, ss_gain, preamp_gain) 
  pod_2 = Pod8401HR('/dev/ttyUSB1', Preamp.Preamp8406_SE4, primary_channel_modes, secondary_channel_modes, ss_gain, preamp_gain) 
  pod_3 = Pod8401HR('/dev/ttyUSB2', Preamp.Preamp8406_SE4, primary_channel_modes, secondary_channel_modes, ss_gain, preamp_gain) 

  # create 3 new edf sink objects, using the 
  # dump_1.edf, dump_2.edf, and dump_3.edf files from the same directory
  edf_sink_1 = EDFSink('dump_1.edf', pod_1)
  edf_sink_2 = EDFSink('dump_2.edf', pod_2)
  edf_sink_3 = EDFSink('dump_3.edf', pod_3)

  # create 3 new influx sink objects, using the default values in the influx sink class 
  influx_sink_1 = InfluxSink(pod_1)
  influx_sink_2 = InfluxSink(pod_2)
  influx_sink_3 = InfluxSink(pod_3)

  # create a list of tuples for the pod/sink mappings 
  mapping = [(pod_1, [edf_sink_1, influx_sink_1]), 
             (pod_2, [edf_sink_2, influx_sink_2]), 
             (pod_3, [edf_sink_3, influx_sink_3])]

  # create a new DataFlow object using the previous mapping 
  flowgraph = DataFlow(mapping)

  # set flag to false
  flag = False

  # begin collection from flowgraph
  flowgraph.collect()

  # stream infinitely
  while True:
    if flag:
      break

  # stop streaming
  flowgraph.stop_collection()



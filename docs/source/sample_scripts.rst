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

  from Morelia.Devices import Pod8206HR
  from Morelia.Stream.sink import EDFSink
  from Morelia.Stream.data_flow import DataFlow

  pod_1 = Pod8206HR('/dev/ttyUSB0', 10)

  edf_dump_1 = EDFSink('dump_1.edf', pod_1)

  mapping = [(pod_1, [edf_dump_1])]

  flowgraph = DataFlow(mapping)

  flag = False
  with flowgraph:

      while True:
          
          if flag:
              break

**Streaming a single 8206HR device to an Influx database for 30 seconds:**

.. code-block:: python

  from Morelia.Devices import Pod8206HR
  from Morelia.Stream.sink import InfluxSink
  from Morelia.Stream.data_flow import DataFlow

  pod_1 = Pod8206HR('/dev/ttyUSB0', 10)

  influx_sink_1 = InfluxSink(pod_1)

  mapping = [(pod_1, [influx_sink_1])]

  flowgraph = DataFlow(mapping)

  flowgraph.collect_for_seconds(30)

**Streaming multiple 8206HR devices to an Influx database and EDF files infinitely:**

.. code-block:: python

  from Morelia.Devices import Pod8206HR
  from Morelia.Stream.sink import InfluxSink, EDFSink
  from Morelia.Stream.data_flow import DataFlow

  pod_1 = Pod8206HR('/dev/ttyUSB0', 10)
  pod_2 = Pod8206HR('/dev/ttyUSB1', 10)
  pod_3 = Pod8206HR('/dev/ttyUSB2', 10)

  edf_dump_1 = EDFSink('dump_1.edf', pod_1)
  edf_dump_2 = EDFSink('dump_2.edf', pod_2)
  edf_dump_3 = EDFSink('dump_3.edf', pod_3)

  influx_sink_1 = InfluxSink(pod_1)
  influx_sink_2 = InfluxSink(pod_2)
  influx_sink_3 = InfluxSink(pod_3)

  mapping = [(pod_1, [edf_dump_1, influx_sink_1]), 
             (pod_2, [edf_dump_2, influx_sink_2]), 
             (pod_3, [edf_dump_3, influx_sink_3])]

  flowgraph = DataFlow(mapping)

  flag = False
  flowgraph.collect()

  while True:
    if flag:
      break

  flowgraph.stop_collection()

=================
8401HR Examples 
=================


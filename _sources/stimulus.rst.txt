################################
Wielding Stimulus Controllers 🤺
################################

A pythonic API for controlling the 8480 is coming soon! For now, please use the :doc:`low-level API </low_level>`.

====================
Low-Level Details ⚙️
====================

For configuring the 8480, several special 8-bit vectors are used (pass these to the low-level API as unsigned integers).

.. list-table:: Stimulus Config Bit Vector Format
   :header-rows: 1
   :widths: auto

   * - Bit Index
     - Name
     - Description

   * - 0 (LSB)
     - Opto / Electrical
     - 0 for electrical stimulus, 1 for optical stimulus.

   * - 1
     - Monophasic / Biphasic
     - 0 for monophasic only on the selected channel, 1 for biphasic. This will use both channels for optical stimulus.

   * - 2
     - Simultaneous
     - 0 for standard operation only on the selected channel, 1 for simultaneous operation on both opt channels. Not applicable for electrical stimulation.

   * - 3-7
     - Unused (write as 0)
     - .

.. list-table:: TTL Config Bit Vector Format
   :header-rows: 1
   :widths: auto

   * - Bit Index
     - Name
     - Description

   * - 0 (LSB)
     - Rising / Falling Edge
     - 0 for TTL events to be triggered by a rising edge, 1 for falling edge triggering.

   * - 1
     - Stimulus Triggering
     - 0 for just TTL event notifications, 1 to use TTL inputs as triggers for the corresponding stimulus channel (TTL0 = CH0, TTL1 = CH1).

   * - 2-6
     - Unused (write as 0)
     - .

   * - 7
     - TTL Input / Sync
     - 0 for normal TTL operation as an input, 1 to have TTL pin operate as a sync output, and input events are disabled.

.. list-table:: Sync Config Bit Vector Format
   :header-rows: 1
   :widths: auto

   * - Bit Index
     - Name
     - Description

   * - 0 (LSB)
     - Sync Level
     - 0 for sync line to be low during stimulus, 1 for sync line to be high during stimulus.

   * - 1
     - Sync Idle
     - 0 for sync to idle the opposite of its active state, 1 to sync to idle tristate (High-Z). Tristate idling is normally only required when connecting to an 8401 so it does not interfere with preamp detection.

   * - 2
     - Signal / Trigger
     - 0 to have sync function as an indicator that a stimulus is in progress. 1 to have sync function as an input trigger like TTL0 (trigger stimulus on ch0 on high input).

   * - 3-7
     - Unused (write as 0)
     - .

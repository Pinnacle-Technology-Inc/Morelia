####################################
The Hitchhiker's Guide to Morelia 🐍
####################################

Welcome to the getting started guide for Pinnacle Technology's Python API: Morelia. This tutorial is meant for complete beginners,
and only assumes basic Python programming skills. If you have not used Python before, or simply need to refresher, `the official
Python tutorial <https://docs.python.org/3/tutorial/index.html>`_ is a good place to start. In terms of content, this guide contains:

.. contents:: 

==============================
Setting Up Your Environment 🌱
==============================
To use Morelia, you must have the Python programming language installed. Morelia is officially supported for
Python >= 3.10, however it may also be compatible with other versions (these just have not been tested). For all environments,
you will need a C++ compiler installed. Additionally, there are a few operating-system-specific requirements:

------------
Windows 🪟
------------
For Windows, it may be required is to install the proper device drivers depending on your system.
You can download and install our USB drivers 
from `our website <https://pinnaclet.com/drivers.html>`_ if needed.

It is also important to make
sure that the virtual COM port functionality is enabled on each device. This can be done by opening
``Device Manager``, finding the device in question (it usually shows up as a "USB Serial Converter" under the
"Universal Serial Bus controller"), right-clicking and selecting ``Properties``. From there, select the
``Advanced`` menu and check the ``Load VCP`` box.

You will also need to install the `Microsoft Visual Studio Build Tools 2022 <https://visualstudio.microsoft.com/visual-cpp-build-tools/>`_.

Please note that in select devices (mainly 8274D and 8229s) enabling VCP can cause issues when connecting to your
devices in Sirenia, so you may need to unload the VCP functionality when you are ready to access your device in Sirenia again.

------------
GNU/Linux 🐧
------------
For Linux, the drivers are included in the Kernel by default. However, if you have
an older device (acquired before 2024), some modifications may need to be made to
the device's firmware for it to be properly recognized by the kernel. If your device
is not being properly recognized, please reach out to us at `sales@pinnaclet.com <mailto:sales@pinnaclet.com>`_.

--------------------------------
Windows Subsystem for Linux 2 💾
--------------------------------
If using the Windows Subsystem for Linux 2 (WSL), special care must be taken to set up an environment
in addition to the normal GNU/Linux instructions.
First, we must load the proper driver into the kernel. We can do this by running the following command as root (# not included):

.. code-block::

   # modprobe ftdi_sio

Next, we want to verify that WSL is starting ``systemd``. Make sure that the file
``/etc/wsl.conf`` contains the lines:

.. code-block::

   [boot]
   systemd=true

Finally, we must download and install an additional tool to make our serial devices
available to WSL called ``usbipd``. Instructions to download, install, and use this
product are available on `their documentation <https://learn.microsoft.com/en-us/windows/wsl/connect-usb>`_.
Make sure to share any devices you wish to access using WSL!

After the devices have been shared, you should see your serial devices in WSL.

================
Installation 💽
================

If you are looking to contribute to Morelia, please see the documentation for :doc:`setting up a development environment </develop>`.

With our environment set up, we can now continue on our journey and install Morelia! Morelia can be installed one of two ways:

* From the `Python Package Index (PyPI) (recommended) <https://pypi.org/>`_
* Manually from the `Source code <https://github.com/Pinnacle-Technology-Inc/Morelia>`_

-----------------------
Installing From PyPI 📦
-----------------------
To install Morelia from PyPI, simply run the following command:

.. code-block::

   $ pip install ptech-morelia

and hooray! You are ready to go 😁

-------------------------
Installing from Source 👷
-------------------------

.. TODO: Switch to source code release when up-to-date release exists.

To begin, `download a copy of the source code <https://github.com/Pinnacle-Technology-Inc/Morelia>`_ from Github, decompress it
using your favorite method, and enter the top level directory though your favorite terminal emulator. After that,
run the following command:

.. code-block::

   $ pip install .

To verify that Morelia is correctly installed, you can run the following command in
the Python interactive shell:

.. code-block::

   >> import Morelia

If that runs with no errors, then you are ready to begin programming!

========================
Connecting to Devices 🔌
========================
After getting set up, the first step is to connect to our devices. To begin, we must first
import the proper classes from Morelia. Currently, the following devices are supported via
the ``Morelia.Devices`` submodule:

======  =============
Device  Class
======  =============
8206HR  ``Pod8206HR``
8401HR  ``Pod8401HR``
8274D   ``Pod8274D``
8229    ``Pod8229``
8480SC  ``Pof8480SC``
======  =============

To connect to any of these devices, instantiate an instance of the class with a string that contains the port name.
On Linux, this will most likely take the form of a file path (e.g. ``/dev/ttyUSB0``) as on Windows, this is simply the
port name (e.g. ``COM0``).

Each devices takes different parameters for instantiation, but there are a few that are common across all devices:

* ``port``: Exactly what it sounds like, the serial port the device is on.
* ``baudrate``: This parameter is optional and only relevant for the 8229 and 8274D. The default should be fine for most use cases, but feel free to contact us
  with any questions.
* ``device_name``: A virtual name that identifies the device, this can be whatever makes the most sense to you. This parameter is optional
  and defaults to ``None``.

For the specific additional parameters of each device, see the documentation for the corresponding class. 

As an example, let's connect to an 8206HR that is connected on
``/dev/ttyUSB0``. Luckily for us, the 8206HR only takes one more parameter in addition to the defaults in its constructor -- `preamp_gain`.

.. code-block:: python

  # Import the proper class from Morelia.
  from Morelia.Devices import Pod8206HR
  
  # Connect to an 8206HR on /dev/ttyUSB0 and set the preamplifer gain to 10.
  pod = Pod8206HR('/dev/ttyUSB0', 10)

It's really as simple as that! Granted, some devices are much more complex that other due to vast number of configuration options (e.g. the 8401HR), but overall
connecting to most devices will look similar to the above example.

========================
Configuring Devices 🎨
========================
Aside from parameters passed to devices on connection, there are also many other knobs and dials for you to adjust on each device
for your experiment! This tends to be very device-specific, so please refer to the individual documentation of each device to see the
available options.

.. TODO: Example. blocked by adding more properties one each device.

========================
Where to Next? 🤔
========================
Now that you have connected and configured all of your devices, the world is your neurological oyster! From this point, there are several different things you can do 
using Morelia:

    * :doc:`Streaming from data acquisition systems </streaming>`
    * :doc:`Controlling sleep deprivation system </sleep_dep>`
    * :doc:`Wielding stimulus controllers </stimulus>`
    * :doc:`Low-level interactions with POD systems </low_level>`

Happy experimenting! 😁

====================
What's in a Name? 🌹
====================

At Pinnacle, it's a bit of a tradition to name our products after animals. Since Morelia is written in
Python, we decided to name it after a `genus of pythons <https://en.wikipedia.org/wiki/Morelia_(snake)>`_. 😁🐍


####################################
The Hitchhiker's Guide to Morelia 🐍
####################################

Welcome to the getting started guide for Pinnacle Technology's Python API: Morelia. This tutorial is meant for complete beginners,
and only assumes basic Python programming skills. If you have not used Python before, or simply need to refresher, `the official
Python tutorial <https://docs.python.org/3/tutorial/index.html>`_ is a good place to start. In terms of content, this guide contains:

* Environment Setup 
* Installation
* Connecting to Devices
* Device Configuration
* Harnessing Data Acquisition Systems
* Controlling a Sleep Deprivation System
* Wielding a Stimulus Controller

==============================
Setting Up Your Environment 🌱
==============================

To use Morelia, you must have the Python programming language installed. Morelia is officially supported for
Python >= 3.10, however it may also be compatible with other versions (these just have not been tested).

On standard Linux and Windows, no special setup is required to run Morelia aside from making sure that
you have the correct device drivers installed and any devices you would like to interact with are visible to the operating system.

However, if using the Windows Subsystem for Linux 2 (WSL), special care must be taken to set up the development environment.

WORK IN PROGRESS:
DO I HAVE END USERS FT-PROG???
DOES WINDOWS HAVE FTDI DRIVERS BY DEFAULT???? SETUP ON WINDOWS?

================
Installation 💽
================

With our environment set up, we can now continue on our journey and install Morelia! Morelia can be installed one of two ways:

* From the `Python Package Index (PyPI) (recommended) <https://pypi.org/>`_
* Manually from the `Source code <https://github.com/Pinnacle-Technology-Inc/Morelia>`_

-----------------------
Installing From PyPI 📦
-----------------------
Unfortunately, Morelia has not been published to PyPI yet! 😭  Check back soon for more updates, 
and please refer to the next subsection for installing from source!

-------------------------
Installing from Source 👷
-------------------------
To begin, `download the latest source code release <https://github.com/Pinnacle-Technology-Inc/Morelia/releases>`_ from Github 
(you just need to download one of the files, which one you choose is up to personal preference), decompress it
using your favorite method, and enter the top level directory though your favorite terminal emulator. After that,
run the following command:

.. code-block::

   $ pip install .


====================
What's in a Name? 🌹
====================

At Pinnacle, it's a bit of a tradition to name our products after animals. Since Morelia is written in
Python, we decided to name it after a `genus of pythons <https://en.wikipedia.org/wiki/Morelia_(snake)>`_. 😁🐍



# Morelia

<!DOCTYPE html>
<html lang="en">
   <div style="text-align: center;">
      <img src="docs/legacy/Logos/Rings.png" alt="logo" width="160"/></center>
   </div>
</html>


## Introduction 

![GitHub license](https://img.shields.io/github/license/Pinnacle-Technology-Inc/Python-POD-API)
![GitHub repo size](https://img.shields.io/github/repo-size/Pinnacle-Technology-Inc/Python-POD-API)
[![Documentation Status](https://readthedocs.org/projects/python-pod-api/badge/?version=latest)](https://python-pod-api.readthedocs.io/en/latest/?badge=latest)

Morelia is a free, open-source Python application programming interface (API) for Pinnacle Technology, Inc. data acquisition POD devices. Morelia core modules, usage examples, and supporting documentation can be found here on GitHub and are available freely under the New BSD License. 

The [SetupAllDevices](/Documents/API_Manuals/SetupAllDevices_Package_Manual.pdf) Python package is designed to be a simple and user-friendly method to setup and stream data from Data Conditioning and Acquisition System POD devices. With this module, you can control several aspects of the hardware. You can connect multiple POD devices and stream data simultaneously. Data can be saved to either EDF or text files. SetupAllDevices uses several supporting classes to interface with the POD devices. The user can use these same modules to code their own personalized data acquisition systems. 

Currently, the API supports 8206-HR, 8401-HR, 8229, 8480-SC, and 8274-D POD devices. In the future, we will offer support to other Pinnacle devices. 

* Code documentation: [here](https://pinnacle-technology-inc.github.io/Morelia)
* PDF Manual: [here](/Documents/API_Manuals/Morelia_Manual.pdf)

## Collaboration 

![GitHub issues](https://img.shields.io/github/issues-raw/Pinnacle-Technology-Inc/Python-POD-API)
![GitHub pull requests](https://img.shields.io/github/issues-pr-raw/Pinnacle-Technology-Inc/Python-POD-API)
![GitHub last commit](https://img.shields.io/github/last-commit/Pinnacle-Technology-Inc/Python-POD-API)
![GitHub commit activity](https://img.shields.io/github/commit-activity/m/Pinnacle-Technology-Inc/Python-POD-API)

This project is open-source; all code is freely and publically accessible for anyone to use. We welcome anyone who wishes to contribute to this project. If you are interested in collaborating, here are some steps to get started:

1. Fork this repository. This will create a repo on your own GitHub account.
2. Clone your forked project to your local machine. The clone link can be found under the "Code" icon on the GitHub repo.
3. Create a new branch where you can develop your code. Stage, commit, and push any changes to your fork.
4. Create a pull request and write comments describing the code changes and the reason for the pull request. This targets the original repository.
5. The repository maintainers will review your pull request. If approved, your code will be merged into this repo.

## Project Setup

Here are some useful documents for setting up your coding environment to use the Python modules in this project:

* Tips for installing your Python environment: [here](/Documents/Programming_Tutorials/PythonEnviornmentTips.txt)

* Python libraries required for this project: [here](/Code/requirements.txt)
   * Run ``pip install -r ./requirements.txt`` in terminal in the Morelia/Code directory. 


# Morelia Package

* Morelia package docs: [here](https://python-pod-api.readthedocs.io/en/latest/Morelia.html)
* Import package: ``import Morelia``

The **Morelia** package is used to operate POD devices. It contains four sub-packages: Devices, Packets, Commands, and Parameters. The **Devices** package is used to create a Pod device object that is connected to a physical device. Devices has a sub-package, **SerialPorts**, which facilitates communication to a POD device through a serial port; this allows the user to read and write data to a POD device. The **Packets** package contains container classes to store serial data packets that are written to or read from a POD device. The **Commands** package stores all the types of commands and their respective information that a POD device can interpret. The **Parameters** package consists of container classes used to store information about the various POD devices; this class is independent of any physical POD device. Lastly, the **Stream** package contains tools to stream and save data from a POD device to a local file; Stream has **Drain** as a sub package, which handles writing to a file (this also has a sub-package, **PodHander**, which interprets streaming data for different POD devices).

The class diagram of the Morelia package is shown below.

![Class diagram for the Morelia package](/Documents/Diagrams/class-diagrams-Morelia.png)

## Examples & Usage 

| Module                                                        | Description                                  |
|---------------------------------------------------------------|----------------------------------------------|
| [Using_8206HR.py](/Code/Examples/UsingPodApi/Using_8206HR.py) | Runs all commands for an 8206-HR POD device. |
| [Using_8401HR.py](/Code/Examples/UsingPodApi/Using_8401HR.py) | Runs all commands for an 8401-HR POD device. |
| [Using_8229.py](/Code/Examples/UsingPodApi/Using_8229.py)     | Runs all commands for an 8229 POD device.    |
| [Using_8480SC.py](/Code/Examples/UsingPodApi/Using_8480SC.py) | Runs all commands for an 8480-SC POD device. |
| [Using_8274D.py](/Code/Examples/UsingPodApi/Using_8274D.py)   | Runs all commands for an 8274-D POD device.  |
| [Using_Stream.py](/Code/Examples/UsingPodApi/Using_Stream.py) | demonstrates how to use Morelia.Stream to save streaming data to a file from a 8206-HR POD device. | 

## Sub-packages

### Devices

* Morelia.Devices package docs: [here](https://python-pod-api.readthedocs.io/en/latest/Morelia.Devices.html)
* Import clases: ``from Morelia.Devices import BasicPodProtocol, Pod8206HR, Pod8401HR, Pod8229, Pod8480SC``

| Class                                                    | Description                                         |
|----------------------------------------------------------|-----------------------------------------------------|
| [Pod](/Code/Morelia/Devices/BasicPodProtocol.py)          | Handle basic communication with a POD device, including reading and writing packets and packet interpretation. |
| [Pod8206HR](/Code/Morelia/Devices/PodDevice_8206HR.py.py) | Handles communication using an 8206-HR POD device.  |
| [Pod8401HR](/Code/Morelia/Devices/PodDevice_8401HR.py)    | Handles communication using an 8401-HR POD device.  |
| [Pod8229](/Code/Morelia/Devices/PodDevice_8229.py)        | Handles communication using an 8229 POD device.     | 
| [Pod8480SC](/Code/Morelia/Devices/PodDevice_8480SC.py)    | Handles communication using an 8480-SC POD device.  | 
| [Pod8274D](/Code/Morelia/Devices/PodDevice_8274D.py)      | Handles communication using an 8274-D POD device.   | 
 
### SerialPorts

* Morelia.SerialPorts package docs: [here](https://python-pod-api.readthedocs.io/en/latest/Morelia.Devices.SerialPorts.html)
* Import clases: ``from Morelia.Devices.SerialPorts import SerialComm``

| Class                                                       | Description                                                     |
|-------------------------------------------------------------|-----------------------------------------------------------------|
| [FindPorts](/Code/Morelia/Devices/SerialPorts/PortAccess.py) | Contains methods for the user to view and select a serial port. |
| [PortIO](/Code/Morelia/Devices/SerialPorts/SerialComm.py)    | Handle serial communication (read/write) using COM ports.       |

### Packets

* Morelia.Packets package docs: [here](https://python-pod-api.readthedocs.io/en/latest/Morelia.Packets.html)
* Import clases: ``from Morelia.Packets import Packet, Standard, Binary, Binary4, Binary5``

| Class                                              | Description                                                                    |
|----------------------------------------------------|--------------------------------------------------------------------------------|
| [Packet](/Code/Morelia/Packets/Packet.py)           | Container class that stores a command packet for a POD device. This class also collection of methods for creating and interpreting POD packets. |
| [PacketStandard](/Code/Morelia/Packets/Standard.py) | Container class that stores a standard command packet for a POD device.        |
| [PacketBinary](/Code/Morelia/Packets/Binary.py)     | Container class that stores a standard binary command packet for a POD device. |
| [PacketBinary4](/Code/Morelia/Packets/Binary4.py)   | Container class that stores a binary4 command packet for a POD device.         |
| [PacketBinary5](/Code/Morelia/Packets/Binary5.py)   | Container class that stores a binary5 command packet for a POD device.         |

### Commands

* Morelia.Commands package docs: [here](https://python-pod-api.readthedocs.io/en/latest/Morelia.Commands.html)
* Import clases: ``from Morelia.Commands import PodCommands``

| Class                                              | Description                                                          |
|----------------------------------------------------|----------------------------------------------------------------------|
| [CommandSet](/Code/Morelia/Commands/PodCommands.py) | Manages a dictionary containing available commands for a POD device. |

### Parameters

* Morelia.Parameters package docs: [here](https://python-pod-api.readthedocs.io/en/latest/Morelia.Parameters.html)
* Import clases: ``from Morelia.Parameters import Params, Params8206HR, Params8401HR, Params8229, Params8480SC``

| Class                                                   | Description                                                              |
|---------------------------------------------------------|--------------------------------------------------------------------------|
| [Params](/Code/Morelia/Parameters/ParamsBasic.py)        | Interface for a container class that stores parameters for a POD device. | 
| [Params8206HR](/Code/Morelia/Parameters/Params8206HR.py) | Container class that stores parameters for a 8206-HR POD device.         | 
| [Params8401HR](/Code/Morelia/Parameters/Params8401HR.py) | Container class that stores parameters for a 8401-HR POD device.         | 
| [Params8229](/Code/Morelia/Parameters/Params8229.py)     | Container class that stores parameters for a 8229 POD device.            | 
| [Params8480SC](/Code/Morelia/Parameters/Params8480SC.py) | Container class that stores parameters for a 8480-SC POD device.         |
| [Params8274D](/Code/Morelia/Parameters/Params8274D.py)   | Container class that stores parameters for a 8274-D POD device.         | 

### Stream

* Morelia.Stream package docs: [here](https://python-pod-api.readthedocs.io/en/latest/Morelia.Stream.html)
* Import clases: ``from Morelia.Stream import Bucket, Valve, Hose, Bucket, DrainBucket``

| Class                                             | Description                                                                                                   |
|---------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| [Bucket](/Code/Morelia/Stream/DataBucket.py)       | Class to collect the data and timestamps when streaming from a POD device.                                    | 
| [Hose](/Code/Morelia/Stream/DataHose.py)           | Collects streaming data from an 8206-HR or 8401-HR POD device. The data and timestamps are updated about every 1 second when streaming. | 
| [Valve](/Code/Morelia/Stream/DeviceValve.py)       | Simple class to start and stop streaming data from a POD device.                                              |
| [DrainBucket](/Code/Morelia/Stream/DrainToFile.py) | This class is used to save the streaming data from a POD device that was collected by a Bucket into a file.   | 

### Drain

* Morelia.Stream.Drain package docs: [here](https://python-pod-api.readthedocs.io/en/latest/Morelia.Stream.Drain.html)
* Import clases: ``from Morelia.Stream.Drain import DrainToFile, DrainToTXT, DrainToEDF``

| Class                                              | Description                                                                              |
|----------------------------------------------------|------------------------------------------------------------------------------------------|
| [DrainToEDF](/Code/Morelia/Stream/Drain/ToEDF.py)   | Class to to drain, or save, the data drops collected by a Bucket into an EDF file.       | 
| [DrainToFile](/Code/Morelia/Stream/Drain/ToFile.py) | Interface class to to drain, or save, the data drops collected by a Bucket into a file.  | 
| [DrainToTXT](/Code/Morelia/Stream/Drain/ToText.py)  | Class to to drain, or save, the data drops collected by a Bucket into a text file.       | 

### PodHandler

* Morelia.Stream.Drain.PodHandler package docs: [here](https://python-pod-api.readthedocs.io/en/latest/Morelia.Stream.Drain.PodHandler.html)
* Import clases: ``from Morelia.Stream.Drain.PodHandler import DrainDeviceHandler, Drain8206HR, Drain8401HR``

| Class                                                                          | Description                                                              |
|--------------------------------------------------------------------------------|--------------------------------------------------------------------------|
| [Drain8206HR](/Code/Morelia/Stream/Drain/PodHandler/Handle8206HR.py)            | Class to help handle 8206-HR POD devices for the Drain classes.          | 
| [Drain8401HR](/Code/Morelia/Stream/Drain/PodHandler/Handle8401HR.py)            | Class to help handle 8206-HR POD devices for the Drain classes.          |
| [Drain8274D](/Code/Morelia/Stream/Drain/PodHandler/Handle8274D.py)              | Class to help handle 8274D POD devices for the Drain classes.            |
| [DrainDeviceHandler](/Code/Morelia/Stream/Drain/PodHandler/HandlerInterface.py) | Interface class for the POD device handlers used by the Drain classes.   |

## Setup Package

The **Setup** package, which uses the Morelia package, walks the user through a process to set up and run a POD device. Setup consists of three sub-packages: SetupAllDevices, SetupOneDevice, and Inputs. The **SetupAllDevices** package is the top-level package in Setup. It allows the user to configure any type of POD device. SetupAllDevices uses the **SetupOneDevice** package, which has classes to operate a single type of device. The **Inputs** package provides helpful functions to request information from the user through the terminal.

The class diagram of the Setup package is shown below.

![Class diagram for the Setup package](/Documents/Diagrams/class-diagrams-Setup.png)

## Examples & Usage 

* SetupAllDevices Python package manual and walkthrough: [here](/Documents/API_Manuals/SetupAllDevices_Package_Manual.pdf)

| Module                                                                    | Description                                                       |
|---------------------------------------------------------------------------|-------------------------------------------------------------------|
| [DetailedExample.py](/Code/Examples/UsingSetup/DetailedExample.py)        | A detailed example that demonstrates how to run Setup_PodDevices. |
| [BasicSetupTemplate.py](/Code/Examples/UsingSetup/BasicSetupTemplate.py)  | A simple example template that runs Setup_PodDevices.             |

## Sub-packages

### SetupAllDevices

* Setup.SetupAllDevices package docs: [here](https://python-pod-api.readthedocs.io/en/latest/Setup.SetupAllDevices.html)
* Import clases: ``from Setup.SetupAllDevices import SetupAll``

| Class                                                       | Description                                                              |
|-------------------------------------------------------------|--------------------------------------------------------------------------|
| [SetupAll](/Code/Setup/SetupAllDevices/Setup_PodDevices.py) | Allows a user to set up and stream from any number of POD devices. The streamed data is saved to a file. | [X]() |

### SetupOneDevice

* Setup.SetupOneDevice package docs: [here](https://python-pod-api.readthedocs.io/en/latest/Setup.SetupOneDevice.html)
* Import clases: ``from Setup.SetupOneDevice import SetupInterface, Setup8206HR, Setup8401HR, Setup8229, Setup8480SC``

| Class                                                              | Description                                             |
|--------------------------------------------------------------------|---------------------------------------------------------|
| [SetupInterface](/Code/Setup/SetupOneDevice/Setup_PodInterface.py) | Provides the basic interface of required methods for subclasses to implement. SetupPodDevices.py is designed to handle any of these children. |
| [Setup8206HR](/Code/Setup/SetupOneDevice/Setup_8206HR.py)          | Provides the setup functions for an 8206-HR POD device. |
| [Setup8401HR](/Code/Setup/SetupOneDevice/Setup_8401HR.py)          | Provides the setup functions for an 8401-HR POD device. |
| [Setup8229](/Code/Setup/SetupOneDevice/Setup_8229.py)              | Provides the setup functions for an 8229 POD device.    |
| [Setup8480SC](/Code/Setup/SetupOneDevice/Setup_8480SC.py)          | Provides the setup functions for an 8480-SC POD device. |
| [Setup8274D](/Code/Setup/SetupOneDevice/Setup_8274D.py)            | Provides the setup functions for an 8274-D POD device.  |

### Inputs

* Setup.Inputs package docs: [here](https://python-pod-api.readthedocs.io/en/latest/Setup.Inputs.html)
* Import clases: ``from Setup.Inputs import UserInput``

| Class                                           | Description                                                           |
|-------------------------------------------------|-----------------------------------------------------------------------|
| [UserInput](/Code/Setup/Inputs/GetUserInput.py) | Contains several methods for getting user input for POD device setup. |

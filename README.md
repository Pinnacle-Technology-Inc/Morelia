# Python POD API

## Project Description 

![GitHub license](https://img.shields.io/github/license/Pinnacle-Technology-Inc/Python-POD-API)
![GitHub repo size](https://img.shields.io/github/repo-size/Pinnacle-Technology-Inc/Python-POD-API)

The Python POD API is a free, open-source application programming interface for Pinnacle Technology, Inc. data acquisition POD devices. The Python POD API core modules, usage examples, and supporting documentation can be found here on GitHub and are available freely under the New BSD License. 

The [SetupAllDevices](/Documents/API_Manuals/SetupAllDevices_Package_Manual.pdf) Python package is designed to be a simple and user-friendly method to setup and stream data from Data Conditioning and Acquisition System POD devices. With this module, you can control several aspects of the hardware. You can connect multiple POD devices and stream data simultaneously. Data can be saved to either EDF or text files. SetupAllDevices uses several supporting classes to interface with the POD devices. The user can use these same modules to code their own personalized data acquisition systems. 

Currently, the API supports 8206-HR and 8401-HR POD devices. In the future, we will offer support to other Pinnacle devices. 

## Collaboration 

![GitHub issues](https://img.shields.io/github/issues-raw/Pinnacle-Technology-Inc/Python-POD-API)
![GitHub pull requests](https://img.shields.io/github/issues-pr-raw/Pinnacle-Technology-Inc/Python-POD-API)
![GitHub last commit](https://img.shields.io/github/last-commit/Pinnacle-Technology-Inc/Python-POD-API)
![GitHub commit activity](https://img.shields.io/github/commit-activity/m/Pinnacle-Technology-Inc/Python-POD-API)

This project is open-source; all code is freely and publically accessable for anyone to use. We welcome anyone who wishes to contribute to this project. If you are interested in collaborating, here are some steps to get started: 

1. Fork this repository. This will create a repo on your own GitHub account.
2. Clone your forked project to your local machine. The clone link can be found under the "Code" icon on the GitHub repo.
3. Create a new branch where you can develop your code. Stage, commit, and push any changes to your fork.
4. Create a pull request and write comments describing the code changes and reason for the pull request. This targets the original repository.
5. The repository maintainers will review your pull request. If approved, your code will be merged into this repo. 

## Setup

Here are some useful documents for setting up your coding environment to use the Python modules in this project:

* Tips for installing your Python environment: [here](/Documents/Programming_Tutorials/PythonEnviornmentTips.txt)

* Python libraries required for this project: [here](/Code/requirements.txt)

## Examples & Usage 

The Setup_PodDevices Python module usage description: [here](/Documents/API_Manuals/Setup_PodDevices-Usage.pdf)

| Module                                                                                | Description                                                       |
|---------------------------------------------------------------------------------------|-------------------------------------------------------------------|
| [Using_SetupPod_WithDescription.py](/Code/Examples/Using_SetupPod_WithDescription.py) | A detailed example that demonstrates how to run Setup_PodDevices. |
| [Using_SetupPod_BasicTemplate.py](/Code/Examples/Using_SetupPod_BasicTemplate.py)     | A simple example template that runs Setup_PodDevices.             |

# Python Packages 

Detailed instructions of all Python packages, modules and methods: 
* Read the Docs website: [here](https://python-pod-api.readthedocs.io/en/latest/)
* PDF Manual: [here](/Documents/API_Manuals/Python_POD_API_Manual.pdf)

## PodApi Package

![Class diagram for the PodApi package](/Documents/Diagrams/class-diagrams-PodApi.png)

### Commands

| Class                                              | Description                                                          |
|----------------------------------------------------|----------------------------------------------------------------------|
| [CommandSet](/Code/PodApi/Commands/PodCommands.py) | Manages a dictionary containing available commands for a POD device. |

### Devices

| Class                                                    | Description                                         |
|----------------------------------------------------------|-----------------------------------------------------|
| [Pod](/Code/PodApi/Devices/BasicPodProtocol.py)          | Handle basic communication with a POD device, including reading and writing packets and packet interpretation. |
| [Pod8206HR](/Code/PodApi/Devices/PodDevice_8206HR.py.py) | Handles communication using an 8206-HR POD device.  |
| [Pod8401HR](/Code/PodApi/Devices/PodDevice_8401HR.py)    | Handles communication using an 8401-HR POD device.  |
| [Pod8229](/Code/PodApi/Devices/PodDevice_8229.py)        | Handles communication using an 8229 POD device.     | 
| [Pod8480SC](/Code/PodApi/Devices/PodDevice_8480SC.py)    |  Handles communication using an 8480-SC POD device. | 
 
### SerialPorts

| Class                                                       | Description                                                     |
|-------------------------------------------------------------|-----------------------------------------------------------------|
| [FindPorts](/Code/PodApi/Devices/SerialPorts/PortAccess.py) | Contains methods for the user to view and select a serial port. |
| [PortIO](/Code/PodApi/Devices/SerialPorts/SerialComm.py)    | Handle serial communication (read/write) using COM ports.       |

### Packets

| Class                                              | Description                                                                    |
|----------------------------------------------------|--------------------------------------------------------------------------------|
| [Packet](/Code/PodApi/Packets/Packet.py)           | Container class that stores a command packet for a POD device. This class also collection of methods for creating and interpreting POD packets. |
| [PacketStandard](/Code/PodApi/Packets/Standard.py) | Container class that stores a standard command packet for a POD device.        |
| [PacketBinary](/Code/PodApi/Packets/Binary.py)     | Container class that stores a standard binary command packet for a POD device. |
| [PacketBinary4](/Code/PodApi/Packets/Binary4.py)   | Container class that stores a binary4 command packet for a POD device.         |
| [PacketBinary5](/Code/PodApi/Packets/Binary5.py)   | Container class that stores a binary5 command packet for a POD device.         |

### Parameters

| Class                                                   | Description                                                              |
|---------------------------------------------------------|--------------------------------------------------------------------------|
| [Params](/Code/PodApi/Parameters/ParamsBasic.py)        | Interface for a container class that stores parameters for a POD device. | 
| [Params8206HR](/Code/PodApi/Parameters/Params8206HR.py) | Container class that stores parameters for a 8206-HR POD device.         | 
| [Params8401HR](/Code/PodApi/Parameters/Params8401HR.py) | Container class that stores parameters for a 8401-HR POD device.         | 
| [Params8229](/Code/PodApi/Parameters/Params8229.py)     | Container class that stores parameters for a 8229 POD device.            | 
| [Params8480SC](/Code/PodApi/Parameters/Params8480SC.py) | Container class that stores parameters for a 8480-SC POD device.         | 

## Setup Package

![Class diagram for the Setup package](/Documents/Diagrams/class-diagrams-Setup.png)

### SetupAllDevice

| Class                                                       | Description                                                              |
|-------------------------------------------------------------|--------------------------------------------------------------------------|
| [SetupAll](/Code/Setup/SetupAllDevices/Setup_PodDevices.py) | Allows a user to set up and stream from any number of POD devices. The streamed data is saved to a file. | [X]() |

### SetupOneDevice

| Class                                                              | Description                                             |
|--------------------------------------------------------------------|---------------------------------------------------------|
| [SetupInterface](/Code/Setup/SetupOneDevice/Setup_PodInterface.py) | Provides the basic interface of required methods for subclasses to implement. SetupPodDevices.py is designed to handle any of these children. |
| [Setup8206HR](/Code/Setup/SetupOneDevice/Setup_8206HR.py)          | Provides the setup functions for an 8206-HR POD device. |
| [Setup8401HR](/Code/Setup/SetupOneDevice/Setup_8401HR.py)          | Provides the setup functions for an 8401-HR POD device. |
| [Setup8229](/Code/Setup/SetupOneDevice/Setup_8229.py)              | Provides the setup functions for an 8229 POD device.    |
| [Setup8480SC](/Code/Setup/SetupOneDevice/Setup_8480SC.py)          | Provides the setup functions for an 8480-SC POD device. |

### Inputs

| Class                                           | Description                                                           |
|-------------------------------------------------|-----------------------------------------------------------------------|
| [UserInput](/Code/Setup/Inputs/GetUserInput.py) | Contains several methods for getting user input for POD device setup. |

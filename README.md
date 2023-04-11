# Python POD API

## Project Description 

The Python POD API is a free, open-source application programming interface for Pinnacle Technology, Inc. data acquisition POD devices. The Python POD API core modules, usage examples, and supporting documentation can be found here on GitHub and are available freely under the New BSD License. 

The [Setup_8206HR Python module](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Code/Modules/Setup_8206HR.py) Python module is designed to be a simple and user-friendly method to setup and stream data from 8206-HR Data Conditioning and Acquisition System POD devices. With this module, you can control several aspects of the hardware, including the EEG low pass filters and sample rate. You can connect multiple POD devices and stream data simultaneously. Data can be saved to either EDF or text files. Setup_8206HR uses several supporting classes to interface with the POD devices. The user can use these same modules to code their own personalized data acquisition systems. 

In the future, we will offer support to other Pinnacle devices. 

## Setup

Tips for installing your Python enviornment [here](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Documents/PythonEnviornmentTips.txt).

Python libraries required for this project [here](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Documents/PyEnvRequirements.txt).

## Usage 

The Setup_8206HR Python module usage description [here](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Documents/Setup_8206HR%20Usage.pdf).

| Module                             | Description                                                   |
|------------------------------------|---------------------------------------------------------------|
| [Using_Setup8206HR.py](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Code/Examples/Using_Setup8206HR.py)               | A detailed example that demonstrates how to run Setup_8206HR. |
| [Using_Setup8206HR_BasicTemplate.py](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Code/Examples/Using_Setup8206HR_BasicTemplate.py) | A simple example template that runs Setup_8206HR.             |

## Modules 

Detailed instructions of all Python modules and methods [here](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Documents/Python-POD-API_Documentation.pdf).

| Module                 | Class        | Description                                                                                                     |
|------------------------|--------------|-----------------------------------------------------------------------------------------------------------------|
| [BasicPodProtocol.py](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Code/Modules/BasicPodProtocol.py)    | POD_Basics   | Handle basic communication with a POD device, including reading and writing packets and packet interpretation.  |
| [PodCommands.py](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Code/Modules/PodCommands.py)         | POD_Commands | Manages a dictionary containing available commands for a POD device.                                            |
| [PodDevice_8206HR.py](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Code/Modules/PodDevice_8206HR.py)    | POD_8206HR   | Handles communication using an 8206HR POD device.                                                               |
| [PodPacketHandling.py](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Code/Modules/PodPacketHandling.py)   | POD_Packets  | Collection of methods for creating and interpreting POD packets.                                                |
| [SerialCommunication.py](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Code/Modules/SerialCommunication.py) | COM_io       | Handle serial communication (read/write) using COM ports.                                                       |
| [Setup_8206HR.py](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Code/Modules/Setup_8206HR.py)        | Setup_8206HR | Allows a user to set up and stream from any number of 8206HR POD devices. The streamed data is saved to a file. |

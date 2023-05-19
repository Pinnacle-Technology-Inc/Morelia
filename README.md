# Python POD API

## Project Description 

![GitHub license](https://img.shields.io/github/license/Pinnacle-Technology-Inc/Python-POD-API)
![GitHub top language](https://img.shields.io/github/languages/top/Pinnacle-Technology-Inc/Python-POD-API)
![GitHub repo size](https://img.shields.io/github/repo-size/Pinnacle-Technology-Inc/Python-POD-API)

The Python POD API is a free, open-source application programming interface for Pinnacle Technology, Inc. data acquisition POD devices. The Python POD API core modules, usage examples, and supporting documentation can be found here on GitHub and are available freely under the New BSD License. 

The [Setup_PodDevices Python module](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/PA-16-Abstract-POD-device-setup/Code/Modules/Setup_PodDevices.py) Python module is designed to be a simple and user-friendly method to setup and stream data from 8206-HR Data Conditioning and Acquisition System POD devices. With this module, you can control several aspects of the hardware, including the EEG low pass filters and sample rate. You can connect multiple POD devices and stream data simultaneously. Data can be saved to either EDF or text files. Setup_PodDevices uses several supporting classes to interface with the POD devices. The user can use these same modules to code their own personalized data acquisition systems. 

In the future, we will offer support to other Pinnacle devices. 

## Collaboration 

![GitHub issues](https://img.shields.io/github/issues-raw/Pinnacle-Technology-Inc/Python-POD-API)
![GitHub closed issues](https://img.shields.io/github/issues-closed-raw/Pinnacle-Technology-Inc/Python-POD-API)
![GitHub pull requests](https://img.shields.io/github/issues-pr-raw/Pinnacle-Technology-Inc/Python-POD-API)
![GitHub closed pull requests](https://img.shields.io/github/issues-pr-closed-raw/Pinnacle-Technology-Inc/Python-POD-API)
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

* Tips for installing your Python environment: [here](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Documents/PythonEnviornmentTips.txt)

* Python libraries required for this project: [here](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Documents/PyEnvRequirements.txt)

## Examples & Usage 

* The Setup_PodDevices Python module usage description: [here](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/PA-16-Abstract-POD-device-setup/Documents/Setup_PodDevices-Usage.pdf)

| Module                             | Description                                                   |
|------------------------------------|---------------------------------------------------------------|
| [Using_SetupPod_WithDescription.py](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/PA-16-Abstract-POD-device-setup/Code/Examples/Using_SetupPod_WithDescription.py)               | A detailed example that demonstrates how to run Setup_PodDevices. |
| [Using_SetupPod_BasicTemplate.py](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/PA-16-Abstract-POD-device-setup/Code/Examples/Using_SetupPod_BasicTemplate.py) | A simple example template that runs Setup_PodDevices.             |


## Modules 

* Detailed instructions of all Python modules and methods: [here](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Documents/Python-POD-API_Documentation.pdf)
* Class digram for all modules: [here](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/PA-16-Abstract-POD-device-setup/Documents/UML-class-diagram.png)

| Module                 | Class        | Description                                                                                                     |
|------------------------|--------------|-----------------------------------------------------------------------------------------------------------------|
| [BasicPodProtocol.py](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Code/Modules/BasicPodProtocol.py)    | POD_Basics   | Handle basic communication with a POD device, including reading and writing packets and packet interpretation.  |
| [PodCommands.py](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Code/Modules/PodCommands.py)         | POD_Commands | Manages a dictionary containing available commands for a POD device. |
| [PodDevice_8206HR.py](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Code/Modules/PodDevice_8206HR.py)    | POD_8206HR   | Handles communication using an 8206-HR POD device. |
| [PodDevice_8401HR.py](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/PA-11-POD-Device-8401HR/Code/Modules/PodDevice_8401HR.py) | POD_8401HR | Handles communication using an 8401-HR POD device. |
| [PodPacketHandling.py](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Code/Modules/PodPacketHandling.py)   | POD_Packets  | Collection of methods for creating and interpreting POD packets. |
| [SerialCommunication.py](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/integration/Code/Modules/SerialCommunication.py) | COM_io       | Handle serial communication (read/write) using COM ports. |
| [Setup_8206HR.py](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/PA-16-Abstract-POD-device-setup/Code/Modules/Setup_8206HR.py) | Setup_8206HR | Provides the setup functions for an 8206-HR POD device. |
| [Setup_PodDevices.py](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/PA-16-Abstract-POD-device-setup/Code/Modules/Setup_PodDevices.py) | Setup_PodDevices | Allows a user to set up and stream from any number of POD devices. The streamed data is saved to a file. |
| [Setup_PodInterface.py](https://github.com/Pinnacle-Technology-Inc/Python-POD-API/blob/PA-16-Abstract-POD-device-setup/Code/Modules/Setup_PodInterface.py) | Setup_PodInterface | Provides the basic interface of required methods for subclasses to implement. SetupPodDevices.py is designed to handle any of these children. |


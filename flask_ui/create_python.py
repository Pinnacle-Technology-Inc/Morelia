import tomllib
from pathlib import Path
from Morelia.Devices import Pod8206HR, PodDevice_8206HR

# function returns a list of pod devices depending on a config_toml file
def return_pod_devices(config_toml: str):

    pod_devices_list = []

    with open(config_toml, "rb") as data:
        config = tomllib.load(data)

    devices = config.get("Pod8206HR", {})
    for i in range(devices['num_devices']):
        port = devices["ports"][i]
        preamp = devices["preamp"][i]
        pod_devices_list.append(Pod8206HR(port, preamp))

    '''devices = config.get("Pod8401HR", {})
    for i in range(devices['num_devices']):
        port = devices["ports"][i]
        preamp = devices["preamp"][i]
        pod_devices_list.append(Pod8401HR(port, preamp))'''

    return pod_devices_list

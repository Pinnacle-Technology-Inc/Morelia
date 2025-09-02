from Morelia.Devices import AcquisitionDevice, PodDevice_8206HR, PodDevice_8401HR, PodDevice_8274D
import json
import re
from typing import List, Tuple
import os

# creates a grafana dashboard based on information passed in
def create_dashboard(filename: str, device_type: str, device_port: str, data_source: str, input_title: str):
    data = {}
    
    if device_type == "8206HR":
        with open(f"templates/8206_{data_source}.json", "r") as f:
            data = json.load(f)
            update_flux_query(data, "name", f"{device_port}")
 
    if device_type == "8401HR":
        with open(f"templates/8401_{data_source}.json", "r") as f:
            data = json.load(f)
            update_flux_query(data, "name", f"{device_port}")
    
    if device_type == "8274D":
        with open(f"templates/8274_{data_source}.json", "r") as f:
            data = json.load(f)
            update_flux_query(data, "name", f"{device_port}")

    data["title"] = input_title
    data["description"] = f"Influx Dashboard for {device_type}"

    with open(f"./grafana/dashboards/{filename}", "w") as json_file:

        json.dump(data, json_file, indent=2)

    print(f"JSON file '{filename}' created.")

# creates a grafana dashboard based on information passed in
def create_dashboard_from_device(filename: str, device: AcquisitionDevice, device_port: str, data_source: str, input_title: str):
    data = {}
    
    if isinstance(device, PodDevice_8206HR):
        with open(f"templates/8206_{data_source}.json", "r") as f:
            data = json.load(f)
            update_flux_query(data, f'r.name == "{device_port}"')
 
    if isinstance(device, PodDevice_8401HR):
        with open(f"templates/8401_{data_source}.json", "r") as f:
            data = json.load(f)
            update_flux_query(data, f'r.name == "{device_port}"')
    
    if isinstance(device, PodDevice_8274D):
        with open(f"templates/8274_{data_source}.json", "r") as f:
            data = json.load(f)
            update_flux_query(data, f'r.name == "{device_port}"')

    data["title"] = input_title
    data["description"] = f"Influx Dashboard for {type(device)}"

    with open(f"./grafana/dashboards/{filename}", "w") as json_file:

        json.dump(data, json_file, indent=2)

    print(f"JSON file '{filename}' created.")

## creates a grafana dashboard (should be placed in BasicPodProtocol)
#def pod_create_dashboard(self, filename: str, data_source: str, input_title: str):
    """Creates a dashboard based on the information from the pod device

    :param filename: name of the file to generate
    :param datasource: where you want to stream the data to (influx or quest)
    :param input_title: the name of the dashboard that you want to create
    """
#    data = {}
#    
#    if isinstance(self, PodDevice_8206HR):
#        with open(f"templates/8206_{data_source}.json", "r") as f:
#            data = json.load(f)
#            #should use the port number, not the port itself
#            update_flux_query(data, f'r.name == "{self.port}"')
# 
#    if isinstance(self, PodDevice_8401HR):
#        with open(f"templates/8401_{data_source}.json", "r") as f:
#            data = json.load(f)
#            update_flux_query(data, f'r.name == "{self.port}"')
#    
#    if isinstance(self, PodDevice_8274D):
#        with open(f"templates/8274_{data_source}.json", "r") as f:
#            data = json.load(f)
#            update_flux_query(data, f'r.name == "{self.port}"')
#
#    data["title"] = input_title
#    data["description"] = f"Influx Dashboard for {self.name}"
#
#    with open(f"./grafana/dashboards/{filename}", "w") as json_file:
#
#        json.dump(data, json_file, indent=2)
#
#    print(f"JSON file '{filename}' created.")

def create_dashboard_from_templates(device: AcquisitionDevice | str, dashboard_name: str = "default_dashboard.json"):
    #device_port = device.port #use port string/number value for this one
    if device == "8206HR" or isinstance(device, PodDevice_8206HR):
        #panel_data = create_panel_data(title="TTL1", queries=[("channel", "TTL1"), ("device", device_port)])
        panel_data = create_panel_data(title="TTL1", queries=[("channel", "TTL1")])
        add_panel_to_dashboard("templates/base_influx_template.json", panel_data, dashboard_name)
        panel_data = create_panel_data(title="TTL2", queries=[("channel", "TTL2")])
        add_panel_to_dashboard("templates/base_influx_template.json", panel_data, dashboard_name)
        panel_data = create_panel_data(title="TTL3", queries=[("channel", "TTL3")])
        add_panel_to_dashboard("templates/base_influx_template.json", panel_data, dashboard_name)
        panel_data = create_panel_data(title="TTL4", queries=[("channel", "TTL4")])
        add_panel_to_dashboard("templates/base_influx_template.json", panel_data, dashboard_name)

        panel_data = create_panel_data(title="CH0", queries=[("channel", "CH0")])
        add_panel_to_dashboard("templates/base_influx_template.json", panel_data, dashboard_name)
        panel_data = create_panel_data(title="CH1", queries=[("channel", "CH1")])
        add_panel_to_dashboard("templates/base_influx_template.json", panel_data, dashboard_name)
        panel_data = create_panel_data(title="CH2", queries=[("channel", "CH2")])
        add_panel_to_dashboard("templates/base_influx_template.json", panel_data, dashboard_name)

    elif device == "8401HR" or isinstance(device, PodDevice_8401HR):

        panel_data = create_panel_data(title="TTL1", queries=[("channel", "TTL1")])
        add_panel_to_dashboard("templates/base_influx_template.json", panel_data, dashboard_name)
        panel_data = create_panel_data(title="TTL2", queries=[("channel", "TTL2")])
        add_panel_to_dashboard("templates/base_influx_template.json", panel_data, dashboard_name)
        panel_data = create_panel_data(title="TTL3", queries=[("channel", "TTL3")])
        add_panel_to_dashboard("templates/base_influx_template.json", panel_data, dashboard_name)
        panel_data = create_panel_data(title="TTL4", queries=[("channel", "TTL4")])
        add_panel_to_dashboard("templates/base_influx_template.json", panel_data, dashboard_name)

        panel_data = create_panel_data(title="CH0", queries=[("channel", "CH0")])
        add_panel_to_dashboard("templates/base_influx_template.json", panel_data, dashboard_name)
        panel_data = create_panel_data(title="CH1", queries=[("channel", "CH1")])
        add_panel_to_dashboard("templates/base_influx_template.json", panel_data, dashboard_name)
        panel_data = create_panel_data(title="CH2", queries=[("channel", "CH2")])
        add_panel_to_dashboard("templates/base_influx_template.json", panel_data, dashboard_name) 
        panel_data = create_panel_data(title="CH3", queries=[("channel", "CH3")])
        add_panel_to_dashboard("templates/base_influx_template.json", panel_data, dashboard_name)

        panel_data = create_panel_data(title="EXT0", queries=[("channel", "EXT0")])
        add_panel_to_dashboard("templates/base_influx_template.json", panel_data, dashboard_name)
        panel_data = create_panel_data(title="EXT1", queries=[("channel", "EXT1")])
        add_panel_to_dashboard("templates/base_influx_template.json", panel_data, dashboard_name)

    elif device == "8274D" or isinstance(device, PodDevice_8274D):
        pass

# adds a panel to json file
def add_panel_to_dashboard(dashboard_json: str, panel_data: dict, dashboard: str):

    dashboard_data = {}
    
    # if the dashboard already exists in the location, then open it
    if os.path.exists(f"{dashboard}"):

        with open(dashboard, "r") as d:

            dashboard_data = json.load(d)
    
    # otherwise, open the base template and use it for data
    else:

        with open(dashboard_json, "r") as d:

            dashboard_data = json.load(d)
    
    # adds data to the panel section of the json
    dashboard_data["panels"].append(panel_data)
    
    # this should generate a new file
    with open(f"{dashboard}", "w") as d:
        json.dump(dashboard_data, d, indent=2)

# returns dictionary with panel data, based on inputs that a user wants
def create_panel_data(title: str, max_data_points: int = 100000, queries: List[Tuple[str, str]] = None):
    data = {}

    with open("templates/base_influx_panel.json", "r") as f:
        data = json.load(f)
    
    for query in queries:
        update_flux_query(data, query[0], query[1])
    data["title"] = title
    data["maxDataPoints"] = max_data_points

    return data

# adds a condition as a part of the flux query
def inject_or_replace_flux_condition(query: str, field: str, new_value: str) -> str:
    pattern = rf'r\.{field}\s*==\s*"[^"]*"'
    replacement = f'r.{field} == "{new_value}"'

    if re.search(pattern, query):

        return re.sub(pattern, replacement, query)

    else:
    
        match = re.search(r'filter\s*\(fn:\s*\(r\)\s*=>\s*\n(.*?)\n\s*\)', query, re.DOTALL)

        if match:
            filter_body = match.group(1)
            new_filter_body = filter_body.rstrip() + f' and\n    {replacement}'
            return query.replace(filter_body, new_filter_body)

    return query

# removes a condition that is part of the flux query
def remove_flux_condition(query: str, field: str) -> str:
    pattern = rf'\s*and\s+r\.{field}\s*==\s*"[^"]*"'
    alt_pattern = rf'r\.{field}\s*==\s*"[^"]*"\s*and\s*'
    exact_pattern = rf'\s*r\.{field}\s*==\s*"[^"]*"\s*'

    if re.search(pattern, query):
        return re.sub(pattern, "", query)
    elif re.search(alt_pattern, query):
        return re.sub(alt_pattern, "", query)
    elif re.search(exact_pattern, query):
        return re.sub(exact_pattern, "", query)
    return query

# updates the flux queries with the specific field for the entire json file
def update_flux_query(obj, field="name", value="ttyUSB0"):
    
    for key, val in (obj.items() if isinstance(obj, dict) else []):
        if key == "query" and isinstance(val, str):
            obj[key] = inject_or_replace_flux_condition(val, field, value)
        elif isinstance(val, (dict, list)):
            update_flux_query(val, field, value)
    if isinstance(obj, list):
        for item in obj:
            update_flux_query(item, field, value)

# removes the flux queries with the specific field for the entire json file
def remove_flux_query_field(obj, field="device"):
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key == "query" and isinstance(val, str):
                obj[key] = remove_flux_condition(val, field)
            else:
                remove_flux_query_field(val, field)
    elif isinstance(obj, list):
        for item in obj:
            remove_flux_query_field(item, field)

# test functions
#def main():
#    create_dashboard("test_dashboard.json", "8401HR", "ttyUSB1", "influx", "hello")
#    create_dashboard_from_templates("8206HR")
#
#main()


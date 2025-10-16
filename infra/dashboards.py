import grafana_json as gj

def main():

    #def create_dashboard(filename: str, device_type: str, device_port: str, data_source: str, input_title: str):
    #def create_dashboard_from_templates(device: AcquisitionDevice | str, dashboard_name: str = "default_dashboard.json"):

    gj.create_dashboard("dashboard1.json", "8206HR", "/dev/ttyUSB0", "influx", "ttyUSB0 Dashboard")
    gj.create_dashboard("dashboard2.json", "8206HR", "/dev/ttyUSB1", "influx", "ttyUSB1 Dashboard")
    gj.create_dashboard("dashboard3.json", "8206HR", "/dev/ttyUSB2", "influx", "ttyUSB2 Dashboard")

#    create_dashboard("test_dashboard.json", "8401HR", "ttyUSB1", "influx", "hello")
main()

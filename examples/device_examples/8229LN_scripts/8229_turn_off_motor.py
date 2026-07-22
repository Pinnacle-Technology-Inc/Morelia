from Morelia.Devices.PodDevice_8229 import Pod8229

if __name__ == "__main__":
    # Create POD object.
    # TODO: replace with your serial port (e.g. COM4 or /dev/ttyUSB0)
    pod = Pod8229(port="REPLACE_WITH_PORT")

    # Set mode to manual control.
    print("Setting mode...")
    response = pod.write_read(
        'SET MODE',
        0
    )
    print("Returned current mode:", response.payload)

    # Set motor state to off.
    print("Setting motor state...")
    response = pod.write_read(
        'SET MOTOR STATE',
        0
    )

    print("Done!")
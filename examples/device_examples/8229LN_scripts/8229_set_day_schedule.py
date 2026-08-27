from Morelia.Devices.PodDevice_8229 import Pod8229

if __name__ == "__main__":
    # Create POD object.
    # TODO: replace with your serial port (e.g. COM4 or /dev/ttyUSB0)
    pod = Pod8229(port="REPLACE_WITH_PORT")

    # Set POD time to the system current system time.
    payload = pod.get_current_time()
    print("Sending POD time payload:", payload)
    response = pod.write_read(
        "SET TIME",
        bytes(payload)
    )

    # Set mode to use the day schedule that we will set (Internal Schedule Mode).
    print("Setting mode...")
    response = pod.write_read(
        'SET MODE',
        2
    )
    print("Returned current mode:", response.payload)

    # Set day schedule
    # Currently configured to turn on during the 9 o'clock hour on Tuesday.
    # Day: 0 = Sunday, 1 = Monday, 2 = Tuesday, etc.
    # Hours: List of 24 values (0-23), 0 = motor off, 1 = motor on.
    # Speed: Motor speed 0-100%, Single integer or list of 24 integers for hourly control.
    schedule = pod.build_set_day_schedule_argument(
        day=2,
        hours=[
            0,  # 00:00
            0,  # 01:00
            0,  # 02:00
            0,  # 03:00
            0,  # 04:00
            0,  # 05:00
            0,  # 06:00
            0,  # 07:00
            0,  # 08:00
            1,  # 09:00
            0,  # 10:00
            0,  # 11:00
            0,  # 12:00
            0,  # 13:00
            0,  # 14:00
            0,  # 15:00
            0,  # 16:00
            0,  # 17:00
            0,  # 18:00
            0,  # 19:00
            0,  # 20:00
            0,  # 21:00
            0,  # 22:00
            0,  # 23:00
        ],
        speed=100
    )
    print("Sending schedule payload:", schedule)
    pod.write_packet(
        "SET DAY SCHEDULE",
        schedule
    )
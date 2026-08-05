def count_samples_worker(pvfs_path, queue):
    from pvfs_tools.Core.pvfs_data_file import PvfsDataFile

    pvfs = PvfsDataFile()

    if not pvfs.open(str(pvfs_path)):
        queue.put(RuntimeError("Could not open PVFS"))
        return

    try:
        channels = list(pvfs._indexed_data_files.values())

        lengths = []

        for channel in channels:
            start = channel.get_start_time()
            end = channel.get_end_time()
            _, samples = channel.get_data(start, end)
            lengths.append(len(samples))

        queue.put(lengths[0])

    finally:
        pvfs.close()
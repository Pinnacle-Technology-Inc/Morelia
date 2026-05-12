# Morelia examples

This folder contains scripts that demonstrate the **Morelia** acquisition API (POD devices, streaming, sinks).

## PVFS file utilities (EDF, WebM, synthetic PVFS)

Stand-alone PVFS converters and CLI tools have moved to the **`pypvfs`** package repository:

- **PyPI:** [pypvfs](https://pypi.org/project/pypvfs/)
- **Examples there:** `pvfs_to_edf_converter.py`, `pvfs_to_video_converter.py`, `pvfs_create_cli.py`

Install with `pip install pypvfs` (and optional extras as documented in that project), then run scripts from the `pypvfs` checkout or follow its README.

## Morelia + PVFS streaming

- **`pvfs_sink_demo.py`** — synthetic 8206HR-style stream to a `.pvfs` file (no hardware).
- **`device_examples/8206HR_scripts/8206_pvfs_stream.py`** — real hardware stream to PVFS.
- **`device_examples/8401HR_scripts/8401_plot_and_save_stream.py`** — plot + optional PVFS save.

These require `pip install ptech-morelia` (which installs **`pypvfs`** for PVFS support).

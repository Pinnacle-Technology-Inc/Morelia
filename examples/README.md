# PVFS to EDF+ Converter

This example application demonstrates how to convert PVFS files to EDF+ format. The converter provides a graphical user interface to:

1. Select a PVFS file or directory of PVFFS files
2. View and select channels to convert
3. Specify the time range for conversion
4. Choose the output EDF+ file location or directory

## Requirements

- Python 3.7 or higher
- Required packages (install using `pip install -r requirements.txt`):
  - numpy
  - pyedflib
  - pytypes

## Usage

1. Install the required dependencies:
   
   pip install -r requirements.txt
   

2. Run the converter:
   
   python pvfs_to_edf_converter.py


3. Using the converter:
   - Click "Select PVFS File" to choose your input file
   - Select the channels you want to convert from the list
   - Adjust the time range if needed
   - Click "Select Output File" to choose where to save the EDF+ file
   - Click "Convert to EDF+" to start the conversion

## Features

- Supports multiple channel selection
- Preserves channel metadata (units, sample rates, etc.)
- Maintains time synchronization
- Handles large files efficiently
- Preserves channel annotations

## Notes

- The original PVFS file is not modified during conversion
- Channel units are preserved when available, defaulting to 'uV' if not specified
- The converter creates a temporary database file during conversion which is automatically cleaned up 
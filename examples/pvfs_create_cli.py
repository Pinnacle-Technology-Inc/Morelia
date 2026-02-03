import os
import sys
import argparse
from datetime import datetime
import numpy as np
from pathlib import Path
import math

# Add the parent directory to sys.path to import pvfs_tools
sys.path.append(str(Path(__file__).parent.parent))
from pvfs_tools.Core.pvfs_data_file import PvfsDataFile
from pvfs_tools.Core.pvfs_binding import HighTime

def create_pvfs_file(output_file="output.pvfs", frequency=2.0, sample_rate=400, duration=60, amplitude=100):
    """
    Create a PVFS file with simulated EEG data.
    
    Args:
        output_file (str): Output PVFS file path
        frequency (float): Sine wave frequency in Hz
        sample_rate (int): Sample rate in Hz
        duration (int): Duration in seconds
        amplitude (float): Amplitude in μV
    """
    try:
        print(f"Creating PVFS file: {output_file}")
        print(f"Parameters: frequency={frequency}Hz, sample_rate={sample_rate}Hz, duration={duration}s, amplitude={amplitude}μV")
        
        # Validate parameters
        if frequency <= 0 or sample_rate <= 0 or duration <= 0 or amplitude <= 0:
            raise ValueError("All parameters must be positive values")
        
        print("Step 1/5: Creating PVFS file...")
        
        # Create PVFS file using the helper class
        pvfs_file = PvfsDataFile()
        print("  - PvfsDataFile instance created")
        
        # Add detailed debugging for the create method
        print(f"  - Attempting to create PVFS file at: {output_file}")
        print(f"  - Current working directory: {os.getcwd()}")
        
        create_result = pvfs_file.create(output_file)
        print(f"  - Create result: {create_result}")
        
        if not create_result:
            print("  - Create method returned False - checking for errors...")
            # Try to get more information about what failed
            if hasattr(pvfs_file, '_pvfs'):
                print(f"  - PVFS object exists: {pvfs_file._pvfs is not None}")
            if hasattr(pvfs_file, '_database'):
                print(f"  - Database object exists: {pvfs_file._database is not None}")
            raise Exception("Failed to create PVFS file")
        
        print("Step 2/5: Setting experiment information...")
        
        # Set experiment information
        start_time = HighTime(datetime.now().timestamp())
        end_time = HighTime(start_time.to_seconds() + duration)
        
        print(f"  - Start time: {start_time}")
        print(f"  - End time: {end_time}")
        
        set_info_result = pvfs_file.set_experiment_info(
            name="Test EEG Recording",
            description="Simulated EEG data for testing PVFS creation",
            start_time=start_time,
            end_time=end_time
        )
        print(f"  - Set experiment info result: {set_info_result}")
        
        if not set_info_result:
            raise Exception("Failed to set experiment information")
        
        print("Step 3/5: Creating EEG channel...")
        
        # Create EEG channel
        indexed_file = pvfs_file.create_channel(
            channel_name="EEG",
            data_rate=sample_rate,
            data_type=1,
            unit="μV"
        )
        print(f"  - Create channel result: {indexed_file is not None}")
        
        if not indexed_file:
            raise Exception("Failed to create EEG channel")
        
        # Generate sine wave data
#        print("Step 4/5: Generating and writing sine wave data...")
        
        num_samples = sample_rate * duration
        time_array = np.linspace(0, duration, num_samples)
        sine_data = amplitude * np.sin(2 * np.pi * frequency * time_array)
        
        # Write data in chunks
        chunk_size = 1000  # Write 1000 samples at a time
        total_chunks = (num_samples + chunk_size - 1) // chunk_size
        
#        for i in range(total_chunks):
#            start_idx = i * chunk_size
#            end_idx = min(start_idx + chunk_size, num_samples)
            
#            chunk_times = time_array[start_idx:end_idx]
#            chunk_data = sine_data[start_idx:end_idx]
            
            # Convert to HighTime objects and write
#            for j, (t, value) in enumerate(zip(chunk_times, chunk_data)):
#                timestamp = HighTime(start_time.to_seconds() + t)
#                indexed_file.append(timestamp, float(value))
            
            # Print progress every 10 chunks
#            if (i + 1) % 10 == 0 or i == total_chunks - 1:
#                progress = ((i + 1) / total_chunks) * 100
#                print(f"  Progress: {progress:.1f}% ({i+1}/{total_chunks} chunks)")
        
        print("Step 5/5: Finalizing PVFS file...")
        
        # Close PVFS file (this will save the database and close all resources)
        pvfs_file.close()
        
        print("Step 6/6: Verifying database content...")
        # Extract and verify the database from the PVFS file
        try:
            import sqlite3
            import tempfile
            
            # Open the PVFS file and extract the database
            verify_pvfs = PvfsDataFile()
            if verify_pvfs.open(output_file):
                print("  - Successfully opened PVFS file for verification")
                
                # Try to get channel names from the database
                channel_names = verify_pvfs.get_channel_names()
                print(f"  - Channel names in database: {channel_names}")
                
                # Try to get experiment info
                exp_info = verify_pvfs.get_experiment_info()
                if exp_info:
                    print(f"  - Experiment name: {exp_info.name}")
                    print(f"  - Experiment description: {exp_info.description}")
                else:
                    print("  - No experiment info found")
                
                # Directly examine the extracted database file
                print("  - Examining extracted database file directly...")
                temp_db_path = f"temp_verify_{verify_pvfs._unique_id}.db3"
                try:
                    result = verify_pvfs._pvfs.extract("experiment.db3", temp_db_path)
                    if result == 0 and os.path.exists(temp_db_path):
                        print(f"  - Extracted database file size: {os.path.getsize(temp_db_path)} bytes")
                        
                        # Try to open the extracted file directly with sqlite3
                        try:
                            conn = sqlite3.connect(temp_db_path)
                            cursor = conn.cursor()
                            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                            tables = cursor.fetchall()
                            print(f"  - Direct SQLite tables: {[table[0] for table in tables]}")
                            
                            if tables:
                                for table in tables:
                                    cursor.execute(f"SELECT COUNT(*) FROM {table[0]}")
                                    count = cursor.fetchone()[0]
                                    print(f"  - Table {table[0]}: {count} records")
                            
                            conn.close()
                        except Exception as e:
                            print(f"  - Direct SQLite error: {e}")
                        
                        # Clean up
                        try:
                            os.remove(temp_db_path)
                        except:
                            pass
                    else:
                        print(f"  - Failed to extract database for direct examination")
                except Exception as e:
                    print(f"  - Error during direct examination: {e}")
                
                verify_pvfs.close()
            else:
                print("  - Failed to open PVFS file for verification")
        except Exception as e:
            print(f"  - Verification failed: {e}")
            import traceback
            traceback.print_exc()
        
        print("✓ PVFS file created successfully!")
        print(f"  File: {output_file}")
        print(f"  Duration: {duration} seconds")
        print(f"  Sample Rate: {sample_rate} Hz")
        print(f"  Frequency: {frequency} Hz")
        print(f"  Amplitude: {amplitude} μV")
        print(f"  Total samples: {num_samples}")
        
        return True
        
    except Exception as e:
        print(f"✗ Error: {str(e)}")
        import traceback
        print("Full traceback:")
        traceback.print_exc()
        return False

def main():
    parser = argparse.ArgumentParser(description="Create a PVFS file with simulated EEG data")
    parser.add_argument("--output", "-o", default="output.pvfs", 
                       help="Output PVFS file path (default: output.pvfs)")
    parser.add_argument("--frequency", "-f", type=float, default=2.0,
                       help="Sine wave frequency in Hz (default: 2.0)")
    parser.add_argument("--sample-rate", "-s", type=int, default=400,
                       help="Sample rate in Hz (default: 400)")
    parser.add_argument("--duration", "-d", type=int, default=60,
                       help="Duration in seconds (default: 60)")
    parser.add_argument("--amplitude", "-a", type=float, default=100,
                       help="Amplitude in μV (default: 100)")
    
    args = parser.parse_args()
    
    print("PVFS File Creator - Command Line Version")
    print("=" * 50)
    
    success = create_pvfs_file(
        output_file=args.output,
        frequency=args.frequency,
        sample_rate=args.sample_rate,
        duration=args.duration,
        amplitude=args.amplitude
    )
    
    if success:
        print("\n✓ Script completed successfully!")
        sys.exit(0)
    else:
        print("\n✗ Script failed!")
        sys.exit(1)

if __name__ == "__main__":
    main() 
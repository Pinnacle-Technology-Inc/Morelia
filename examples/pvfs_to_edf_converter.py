import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
import pyedflib
import numpy as np
from pathlib import Path

# Add the parent directory to sys.path to import pvfs_tools
sys.path.append(str(Path(__file__).parent.parent))
from pvfs_tools.Core.pvfs_binding import PvfsFile, HighTime
from pvfs_tools.Database.database import ExperimentDatabase
from pvfs_tools.Core.indexed_data_file import IndexedDataFile

class PvfsToEdfConverter:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("PVFS to EDF+ Converter")
        # Increase window height to accommodate all elements
        self.root.geometry("800x750")  # Increased from 700 to 750
        
        # Set theme if available
        try:
            self.root.tk.call('source', 'azure.tcl')
            self.root.tk.call('set_theme', 'light')
        except:
            pass  # Use default theme if custom theme not available
        
        style = ttk.Style()
        style.theme_use('clam')  # or 'alt', 'default', 'classic'
        
        self.pvfs_file = None
        self.vfs = None
        self.db = None
        self.channels = []
        self.selected_channels = []
        self.start_time = None
        self.end_time = None
        self.channel_name_map = {}  # Map processed names to original names
        self.cancel_conversion = False  # Flag for canceling batch conversion
        
        # Create main container with padding
        main_container = ttk.Frame(self.root, padding="10")
        main_container.pack(fill="both", expand=True)
        
        self.setup_ui(main_container)
        
        # Center the window on screen
        self.center_window()
        
    def center_window(self):
        """Center the window on the screen."""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
        
    def show_message(self, title, message, message_type="info"):
        """Show a message box centered on the application window."""
        # Create a temporary top-level window
        dialog = tk.Toplevel(self.root)
        dialog.withdraw()  # Hide the window initially
        
        # Show the message box
        if message_type == "error":
            messagebox.showerror(title, message, parent=dialog)
        elif message_type == "warning":
            messagebox.showwarning(title, message, parent=dialog)
        else:
            messagebox.showinfo(title, message, parent=dialog)
            
        # Center the dialog on the main window
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (dialog.winfo_width() // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f'+{x}+{y}')
        
        # Destroy the temporary window
        dialog.destroy()
        
    def setup_ui(self, parent):
        # File selection
        file_frame = ttk.LabelFrame(parent, text="File Selection", padding="10")
        file_frame.pack(fill="x", pady=5)
        
        # Left side of file frame
        left_frame = ttk.Frame(file_frame)
        left_frame.pack(side="left", fill="x", expand=True)
        ttk.Button(left_frame, text="Select PVFS File", command=self.select_pvfs_file).pack(side="left", padx=5)
        self.file_label = ttk.Label(left_frame, text="No file selected")
        self.file_label.pack(side="left", padx=5)
        
        # Right side of file frame
        right_frame = ttk.Frame(file_frame)
        right_frame.pack(side="right")
        ttk.Button(right_frame, text="Convert Directory", command=self.convert_directory).pack(side="right", padx=5)
        
        # Channel selection
        channel_frame = ttk.LabelFrame(parent, text="Channel Selection", padding="10")
        channel_frame.pack(fill="both", expand=True, pady=5)
        
        # Channel list with checkboxes
        self.channel_listbox = tk.Listbox(channel_frame, selectmode="multiple", 
                                        font=('TkDefaultFont', 10),
                                        highlightthickness=1,
                                        highlightbackground='#cccccc')
        self.channel_listbox.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        
        scrollbar = ttk.Scrollbar(channel_frame, orient="vertical", command=self.channel_listbox.yview)
        scrollbar.pack(side="right", fill="y", pady=5)
        self.channel_listbox.configure(yscrollcommand=scrollbar.set)
        
        # Time range selection
        time_frame = ttk.LabelFrame(parent, text="Time Range", padding="10")
        time_frame.pack(fill="x", pady=5)
        
        ttk.Label(time_frame, text="Start Time:").grid(row=0, column=0, padx=5, pady=5)
        self.start_time_entry = ttk.Entry(time_frame, width=25)
        self.start_time_entry.grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(time_frame, text="End Time:").grid(row=0, column=2, padx=5, pady=5)
        self.end_time_entry = ttk.Entry(time_frame, width=25)
        self.end_time_entry.grid(row=0, column=3, padx=5, pady=5)
        
        # Add export annotations checkbox next to end time
        self.export_annotations_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(time_frame, text="Export Annotations", variable=self.export_annotations_var).grid(row=0, column=4, padx=5, pady=5)
        
        # Add time format help label
        ttk.Label(time_frame, text="Format: YYYY-MM-DD HH:MM:SS.ss", 
                 font=('TkDefaultFont', 9)).grid(row=1, column=0, columnspan=5, pady=5)
        
        # Output file selection
        output_frame = ttk.LabelFrame(parent, text="Output", padding="10")
        output_frame.pack(fill="x", pady=5)
        
        ttk.Button(output_frame, text="Select Output File", command=self.select_output_file).pack(side="left", padx=5)
        self.output_label = ttk.Label(output_frame, text="No output file selected")
        self.output_label.pack(side="left", padx=5)
        
        # Convert button with more padding
        convert_frame = ttk.Frame(parent)
        convert_frame.pack(fill="x", pady=10)
        ttk.Button(convert_frame, text="Convert to EDF+", command=self.convert_to_edf).pack(pady=5)
        
        # Add progress bar with better styling
        self.progress_frame = ttk.LabelFrame(parent, text="Progress", padding="10")
        self.progress_frame.pack(fill="x", pady=5)
        
        # Progress bar and cancel button container
        progress_container = ttk.Frame(self.progress_frame)
        progress_container.pack(fill="x", padx=5, pady=5)
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            progress_container, 
            variable=self.progress_var,
            maximum=100,
            mode='determinate',
            length=300,
            style='Horizontal.TProgressbar'
        )
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        # Add cancel button
        self.cancel_button = ttk.Button(progress_container, text="Cancel", command=self.cancel_batch)
        self.cancel_button.pack(side="right")
        self.cancel_button.pack_forget()  # Hide initially
        
        # Style the progress bar
        style = ttk.Style()
        style.configure('Horizontal.TProgressbar', 
                       thickness=20,  # Make progress bar taller
                       troughcolor='#E0E0E0',  # Light gray background
                       background='#4CAF50')  # Green progress
        
        self.progress_label = ttk.Label(self.progress_frame, text="")
        self.progress_label.pack(pady=5)
        
    def select_pvfs_file(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("PVFS files", "*.pvfs"), ("All files", "*.*")]
        )
        if file_path:
            self.pvfs_file = file_path
            self.file_label.config(text=os.path.basename(file_path))
            self.load_pvfs_file()
            
    def process_channel_name(self, channel_name: str) -> str:
        """Process channel name by removing trailing digit if present.
        
        Args:
            channel_name: The raw channel name (e.g., 'CH A0', 'CH A10')
            
        Returns:
            Processed channel name with trailing digit removed (e.g., 'CH A', 'CH A1')
        """
        # If the last character is a digit, remove it
        if channel_name and channel_name[-1].isdigit():
            return channel_name[:-1]
        return channel_name
            
    def load_pvfs_file(self):
        try:
            # Open PVFS file
            self.vfs = PvfsFile.open(self.pvfs_file)
            
            # Extract database
            db_path = os.path.join(os.path.dirname(self.pvfs_file), "temp.db3")
            result = self.vfs.extract("experiment.db3", db_path)
            if result != 0:
                raise Exception("Failed to extract database from PVFS file")
            
            # Open database
            self.db = ExperimentDatabase(db_path)
            
            # Get channel list from database instead of VFS
            channel_names = self.db.get_channel_names()
            
            # Update channel listbox
            self.channel_listbox.delete(0, tk.END)
            self.channel_name_map.clear()  # Clear the mapping
            
            for channel_name in channel_names:
                # Get channel info from database
                channel_info = self.db.get_channel_info(channel_name)
                if not channel_info:
                    continue
                
                # Check if this channel exists in the VFS
                index_filename = f"{channel_info.filename}.index"
                if index_filename not in self.vfs.get_file_list():
                    continue
                
                # Check channel type from index file
                try:
                    indexed_file = IndexedDataFile(self.vfs, channel_info.filename)
                    header = indexed_file._header
                    # Only include channels of type 1 or 8
                    if header.data_type not in [1, 8]:
                        indexed_file.close()
                        continue
                    indexed_file.close()
                except Exception as e:
                    print(f"Warning: Could not read header for channel {channel_name}: {str(e)}")
                    continue
                
                # Add channel to listbox
                self.channel_listbox.insert(tk.END, channel_name)
                # Store mapping of friendly name to filename
                self.channel_name_map[channel_name] = channel_info.filename
            
            # Select all channels by default
            for i in range(self.channel_listbox.size()):
                self.channel_listbox.selection_set(i)
            
            # Get time range from the first data channel
            if self.channel_listbox.size() > 0:
                first_channel = self.channel_listbox.get(0)
                original_name = self.channel_name_map[first_channel]  # Get filename from mapping
                indexed_file = IndexedDataFile(self.vfs, original_name)
                start_time = indexed_file.get_start_time()
                end_time = indexed_file.get_end_time()
                
                self.start_time_entry.delete(0, tk.END)
                self.start_time_entry.insert(0, start_time.to_string_local())
                
                self.end_time_entry.delete(0, tk.END)
                self.end_time_entry.insert(0, end_time.to_string_local())
                
                indexed_file.close()
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load PVFS file: {str(e)}")
            # Clean up temporary database file if it exists
            if os.path.exists(db_path):
                try:
                    os.remove(db_path)
                except:
                    pass
            
    def select_output_file(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension=".edf",
            filetypes=[("EDF files", "*.edf"), ("All files", "*.*")]
        )
        if file_path:
            self.output_file = file_path
            self.output_label.config(text=os.path.basename(file_path))
            
    def parse_local_time(self, time_str: str) -> float:
        """Parse a local time string into Unix timestamp."""
        try:
            # Parse the local time string
            dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S.%f')
            # Convert to UTC timestamp
            return dt.timestamp()
        except ValueError as e:
            raise ValueError(f"Invalid time format: {time_str}. Expected format: YYYY-MM-DD HH:MM:SS.ss")
            
    def update_progress(self, value: float, text: str = ""):
        """Update the progress bar and label.
        
        Args:
            value: Progress value (0-100)
            text: Optional text to display
        """
        # Only update if the value has changed significantly (more than 1%)
        if abs(self.progress_var.get() - value) > 1.0:
            self.progress_var.set(value)
            if text:
                self.progress_label.config(text=text)
            self.root.update_idletasks()
        
    def convert_to_edf(self, suppress_message=False):
        if not hasattr(self, 'output_file'):
            self.show_message("Error", "Please select an output file", "error")
            return
            
        try:
            # Reset progress
            self.update_progress(0, "Starting conversion...")
            
            # Get selected channels
            selected_indices = self.channel_listbox.curselection()
            if not selected_indices:
                self.show_message("Error", "Please select at least one channel", "error")
                return
                
            selected_channels = [self.channel_listbox.get(i) for i in selected_indices]
            
            # Get time range
            try:
                start_time = self.parse_local_time(self.start_time_entry.get())
                end_time = self.parse_local_time(self.end_time_entry.get())
            except ValueError as e:
                self.show_message("Error", str(e), "error")
                return
                
            # Create EDF file
            try:
                f = pyedflib.EdfWriter(self.output_file, len(selected_channels))
            except Exception as e:
                raise Exception(f"Failed to create EDF file: {str(e)}")
            
            # Process each channel
            channel_info = []
            channel_data = []
            all_annotations = []  # Store all annotations for writing later
            
            total_channels = len(selected_channels)
            last_progress = 0
            for channel_idx, channel_name in enumerate(selected_channels):
                try:
                    # Update progress less frequently
                    progress = (channel_idx / total_channels) * 50  # First 50% for data processing
                    if progress - last_progress >= 5:  # Only update every 5%
                        self.update_progress(progress, f"Processing channel {channel_name}...")
                        last_progress = progress
                    
                    # Get channel information using processed name
                    channel_info_db = self.db.get_channel_info(channel_name)
                    if not channel_info_db:
                        continue
                    
                    # Read data using original name
                    original_name = self.channel_name_map[channel_name]
                    indexed_file = IndexedDataFile(self.vfs, original_name)
                    start_ht = HighTime(start_time)
                    end_ht = HighTime(end_time)
                    
                    # Get the data
                    timestamps, values = indexed_file.get_data(start_ht, end_ht)
                    
                    # Convert to numpy array and handle any invalid values
                    data = np.array(values, dtype=np.float64)
                    # Replace any NaN or infinite values with 0
                    data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
                    
                    # Calculate physical min/max with safety checks
                    try:
                        data_max = float(np.max(data))
                        data_min = float(np.min(data))
                        
                        # Define bounds and defaults
                        MAX_ALLOWED = 1e6  # Maximum allowed absolute value
                        DEFAULT_MAX = 100.0
                        DEFAULT_MIN = -100.0
                        
                        # Check if values are within reasonable bounds
                        if (not np.isfinite(data_max) or 
                            not np.isfinite(data_min) or 
                            abs(data_max) > MAX_ALLOWED or 
                            abs(data_min) > MAX_ALLOWED):
                            print(f"Warning: Channel {channel_name} has out-of-range values. Using defaults.")
                            data_max = DEFAULT_MAX
                            data_min = DEFAULT_MIN
                        else:
                            # Add a small buffer to min/max to avoid edge cases
                            buffer = abs(data_max - data_min) * 0.01  # 1% buffer
                            data_max += buffer
                            data_min -= buffer
                            
                            # Ensure values are still within bounds after adding buffer
                            if abs(data_max) > MAX_ALLOWED or abs(data_min) > MAX_ALLOWED:
                                print(f"Warning: Channel {channel_name} buffer exceeded bounds. Using defaults.")
                                data_max = DEFAULT_MAX
                                data_min = DEFAULT_MIN
                        
                        # Round to 4 decimal places to fit within EDF+'s 8-character limit
                        # This ensures values like 101.9919 instead of 101.991913
                        # For negative numbers, we need to account for the minus sign
                        if data_max < 0:
                            data_max = round(data_max, 3)  # One less decimal place for negative numbers
                        else:
                            data_max = round(data_max, 4)
                            
                        if data_min < 0:
                            data_min = round(data_min, 3)  # One less decimal place for negative numbers
                        else:
                            data_min = round(data_min, 4)
                        
                    except Exception as e:
                        print(f"Warning: Error calculating min/max for channel {channel_name}: {str(e)}")
                        # Use safe default values if calculation fails
                        data_max = 100.0
                        data_min = -100.0
                    
                    # Get channel information
                    channel_info.append({
                        'label': channel_name,  # Use processed name for display
                        'dimension': channel_info_db.unit or 'uV',
                        'sample_frequency': channel_info_db.data_rate,
                        'physical_max': data_max,
                        'physical_min': data_min,
                        'digital_max': 32767,
                        'digital_min': -32768,
                        'prefilter': '',
                        'transducer': channel_info_db.device_name or ''
                    })
                    
                    channel_data.append(data)
                    
                    # Get annotations for this channel if enabled
                    if self.export_annotations_var.get():
                        # Get channel-specific annotations
                        channel_annotations = self.db.get_channel_annotations(channel_info_db.id)
                        # Get global annotations (channel_id = -1) only for the first channel
                        global_annotations = []
                        if channel_info_db.id == 0:  # Only get global annotations once
                            global_annotations = self.db.get_channel_annotations(-1)
                        
                        # Combine both types of annotations
                        annotations = channel_annotations + global_annotations
                        
                        if annotations:
                            for annotation in annotations:
                                # Add a small buffer (1 second) to include annotations near the edges
                                time_buffer = 1.0  # seconds
                                if (annotation.start_time and 
                                    annotation.start_time.to_seconds() >= (start_time - time_buffer) and 
                                    annotation.start_time.to_seconds() <= (end_time + time_buffer)):
                                    
                                    # Convert annotation to EDF format - use relative time from start
                                    onset = max(0, annotation.start_time.to_seconds() - start_time)  # Ensure non-negative onset
                                    duration = 0.001  # Minimum duration for EDF compatibility (1ms)
                                    if annotation.end_time:
                                        duration = max(0.001, annotation.end_time.to_seconds() - annotation.start_time.to_seconds())
                                    
                                    # Create annotation text
                                    annotation_text = ""
                                    if annotation.comment:
                                        annotation_text += f": {annotation.comment}"
                                    
                                    all_annotations.append((onset, duration, annotation_text))
                    
                    indexed_file.close()
                    
                except Exception as e:
                    raise Exception(f"Error processing channel {channel_name}: {str(e)}")
            
            if not channel_info or not channel_data:
                raise Exception("No valid channels to write")
            
            # Update progress for header writing
            self.update_progress(50, "Writing EDF headers...")
            
            # Set header information
            try:
                # Create datetime object from timestamp
                start_datetime = datetime.fromtimestamp(start_time)
                
                header = {
                    'technician': 'PVFS Converter',
                    'recording_additional': 'PVFS to EDF+',
                    'patientname': 'Unknown',
                    'patient_additional': '',
                    'patientcode': '',
                    'sex': 'X',
                    'birthdate': '',
                    'admincode': '',
                    'equipment': 'PVFS',
                    'hospitalname': '',
                    'startdate': start_datetime
                }
                f.setHeader(header)
            except Exception as e:
                raise Exception(f"Failed to set EDF header: {str(e)}")
            
            # Set channel information
            try:
                f.setSignalHeaders(channel_info)
            except Exception as e:
                raise Exception(f"Failed to set channel headers: {str(e)}")
            
            # Update progress for data writing
            self.update_progress(75, "Writing data samples...")
            
            # Write data
            try:
                f.writeSamples(channel_data)
            except Exception as e:
                raise Exception(f"Failed to write samples: {str(e)}")
            
            # Update progress for annotation writing
            self.update_progress(90, "Writing annotations...")
            
            # Write annotations if any
            if self.export_annotations_var.get() and all_annotations:
                try:
                    # Sort annotations by onset time
                    all_annotations.sort(key=lambda x: x[0])
                    for onset, duration, text in all_annotations:
                        f.writeAnnotation(onset, duration, text)
                except Exception as e:
                    print(f"Warning: Failed to write annotations: {str(e)}")
            
            # Update progress for completion
            self.update_progress(100, "Conversion completed!")
            
            # Close file
            try:
                f.close()
            except Exception as e:
                raise Exception(f"Failed to close EDF file: {str(e)}")
            
            if not suppress_message:
                self.show_message("Success", "Conversion completed successfully!")
            
        except Exception as e:
            error_msg = f"Conversion failed: {str(e)}"
            self.show_message("Error", error_msg, "error")
        finally:
            # Reset progress bar
            self.update_progress(0, "")
            
    def cancel_batch(self):
        """Cancel the current batch conversion."""
        self.cancel_conversion = True
        self.update_progress(0, "Canceling conversion...")
        self.cancel_button.pack_forget()
        
    def convert_directory(self):
        """Convert all PVFS files in a selected directory."""
        directory = filedialog.askdirectory(title="Select Directory with PVFS Files")
        if not directory:
            return
            
        # Get list of PVFS files
        pvfs_files = [f for f in os.listdir(directory) if f.lower().endswith('.pvfs')]
        if not pvfs_files:
            self.show_message("No Files", "No PVFS files found in selected directory")
            return
            
        # Ask for output directory
        output_dir = filedialog.askdirectory(title="Select Output Directory")
        if not output_dir:
            return
            
        # Reset cancel flag and show cancel button
        self.cancel_conversion = False
        self.cancel_button.pack(side="right")
        
        # Process each file
        total_files = len(pvfs_files)
        successful = 0
        failed = 0
        
        for idx, pvfs_file in enumerate(pvfs_files):
            if self.cancel_conversion:
                break
                
            try:
                # Update progress
                progress = (idx / total_files) * 100
                self.update_progress(progress, f"Loading {pvfs_file}...")
                
                # Set up file paths
                input_path = os.path.join(directory, pvfs_file)
                output_path = os.path.join(output_dir, os.path.splitext(pvfs_file)[0] + '.edf')
                
                # Load the PVFS file
                self.pvfs_file = input_path
                self.file_label.config(text=os.path.basename(input_path))
                self.load_pvfs_file()
                
                # Wait for UI to update and ensure channels are selected
                self.root.update()
                if not self.channel_listbox.curselection():
                    for i in range(self.channel_listbox.size()):
                        self.channel_listbox.selection_set(i)
                    self.root.update()
                
                # Set output file (will overwrite if exists)
                self.output_file = output_path
                self.output_label.config(text=os.path.basename(output_path))
                
                # Update progress for conversion
                self.update_progress(progress, f"Converting {pvfs_file}...")
                
                # Convert the file with message suppression
                self.convert_to_edf(suppress_message=True)
                successful += 1
                
            except Exception as e:
                failed += 1
                self.show_message("Error", f"Failed to convert {pvfs_file}: {str(e)}", "error")
                continue
                
        # Reset progress and hide cancel button
        self.update_progress(0, "")
        self.cancel_button.pack_forget()
        
        # Show summary
        if self.cancel_conversion:
            self.show_message("Cancelled", 
                            f"Conversion cancelled:\n"
                            f"Successfully converted: {successful} files\n"
                            f"Failed to convert: {failed} files")
        elif failed == 0:
            self.show_message("Complete", f"Successfully converted all {successful} files")
        else:
            self.show_message("Complete", 
                            f"Conversion complete:\n"
                            f"Successfully converted: {successful} files\n"
                            f"Failed to convert: {failed} files")
        
    def run(self):
        self.root.mainloop()
        
if __name__ == "__main__":
    app = PvfsToEdfConverter()
    app.run() 
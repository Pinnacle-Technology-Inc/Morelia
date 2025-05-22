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
        self.root.geometry("800x600")
        
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
        
        self.setup_ui()
        
    def setup_ui(self):
        # File selection
        file_frame = ttk.LabelFrame(self.root, text="File Selection", padding="10")
        file_frame.pack(fill="x", padx=10, pady=5)
        
        ttk.Button(file_frame, text="Select PVFS File", command=self.select_pvfs_file).pack(side="left", padx=5)
        self.file_label = ttk.Label(file_frame, text="No file selected")
        self.file_label.pack(side="left", padx=5)
        
        # Channel selection
        channel_frame = ttk.LabelFrame(self.root, text="Channel Selection", padding="10")
        channel_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
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
        time_frame = ttk.LabelFrame(self.root, text="Time Range", padding="10")
        time_frame.pack(fill="x", padx=10, pady=5)
        
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
        output_frame = ttk.LabelFrame(self.root, text="Output", padding="10")
        output_frame.pack(fill="x", padx=10, pady=5)
        
        ttk.Button(output_frame, text="Select Output File", command=self.select_output_file).pack(side="left", padx=5)
        self.output_label = ttk.Label(output_frame, text="No output file selected")
        self.output_label.pack(side="left", padx=5)
        
        # Convert button with more padding
        convert_frame = ttk.Frame(self.root)
        convert_frame.pack(fill="x", padx=10, pady=10)
        ttk.Button(convert_frame, text="Convert to EDF+", command=self.convert_to_edf).pack(pady=5)
        
        # Add progress bar with better styling
        self.progress_frame = ttk.LabelFrame(self.root, text="Progress", padding="10")
        self.progress_frame.pack(fill="x", padx=10, pady=5)
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            self.progress_frame, 
            variable=self.progress_var,
            maximum=100,
            mode='determinate',
            length=300,
            style='Horizontal.TProgressbar'
        )
        self.progress_bar.pack(fill="x", padx=5, pady=5)
        
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
            
            # Get channel list
            self.channels = self.vfs.get_channel_list()
            
            # Update channel listbox
            self.channel_listbox.delete(0, tk.END)
            processed_names = set()  # Keep track of processed names to avoid duplicates
            self.channel_name_map.clear()  # Clear the mapping
            
            for channel in self.channels:
                # Check if this is a data channel (has both .index and .dat extensions)
                base_name = channel
                if channel.endswith('.index'):
                    base_name = channel[:-6]
                elif channel.endswith('.dat'):
                    base_name = channel[:-4]
                else:
                    continue
                
                # Process the channel name
                processed_name = self.process_channel_name(base_name)
                
                # Only add the channel if we haven't seen this processed name before
                if processed_name not in processed_names:
                    self.channel_listbox.insert(tk.END, processed_name)
                    processed_names.add(processed_name)
                    self.channel_name_map[processed_name] = base_name  # Store mapping
            
            # Select all channels by default
            for i in range(self.channel_listbox.size()):
                self.channel_listbox.selection_set(i)
            
            # Get time range from the first data channel
            if self.channel_listbox.size() > 0:
                first_channel = self.channel_listbox.get(0)
                original_name = self.channel_name_map[first_channel]  # Get original name
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
        
    def convert_to_edf(self):
        if not hasattr(self, 'output_file'):
            messagebox.showerror("Error", "Please select an output file")
            return
            
        try:
            # Reset progress
            self.update_progress(0, "Starting conversion...")
            
            # Get selected channels
            selected_indices = self.channel_listbox.curselection()
            if not selected_indices:
                messagebox.showerror("Error", "Please select at least one channel")
                return
                
            selected_channels = [self.channel_listbox.get(i) for i in selected_indices]
            
            # Get time range
            try:
                start_time = self.parse_local_time(self.start_time_entry.get())
                end_time = self.parse_local_time(self.end_time_entry.get())
            except ValueError as e:
                messagebox.showerror("Error", str(e))
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
                    
                    # Convert to numpy array
                    data = np.array(values, dtype=np.float64)
                    
                    # Get channel information
                    channel_info.append({
                        'label': channel_name,  # Use processed name for display
                        'dimension': channel_info_db.unit or 'uV',
                        'sample_frequency': channel_info_db.data_rate,
                        'physical_max': round(data.max(), 6),  # Round to 6 decimal places
                        'physical_min': round(data.min(), 6),  # Round to 6 decimal places
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
            
            messagebox.showinfo("Success", "Conversion completed successfully!")
            
        except Exception as e:
            error_msg = f"Conversion failed: {str(e)}"
            messagebox.showerror("Error", error_msg)
        finally:
            # Reset progress bar
            self.update_progress(0, "")
            
    def run(self):
        self.root.mainloop()
        
if __name__ == "__main__":
    app = PvfsToEdfConverter()
    app.run() 
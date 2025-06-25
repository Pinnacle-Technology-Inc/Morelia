import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
import numpy as np
from pathlib import Path
import subprocess
import tempfile
from pvfs_tools.Core.webm_helpers import WebMWriter

# Add the parent directory to sys.path to import pvfs_tools
sys.path.append(str(Path(__file__).parent.parent))
from pvfs_tools.Core.pvfs_binding import PvfsFile, HighTime
from pvfs_tools.Database.database import ExperimentDatabase
from pvfs_tools.Core.video_data_file import VideoDataFile

class PvfsToVideoConverter:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("PVFS to WebM Converter")
        self.root.geometry("800x600")
        
        # Set theme if available
        try:
            self.root.tk.call('source', 'azure.tcl')
            self.root.tk.call('set_theme', 'light')
        except:
            pass  # Use default theme if custom theme not available
        
        style = ttk.Style()
        style.theme_use('clam')
        
        self.pvfs_file = None
        self.vfs = None
        self.db = None
        self.video_channels = []
        self.selected_channel = None
        self.start_time = None
        self.end_time = None
        self.cancel_conversion = False
        self.channel_name_map = {}
        
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
        dialog = tk.Toplevel(self.root)
        dialog.withdraw()
        
        if message_type == "error":
            messagebox.showerror(title, message, parent=dialog)
        elif message_type == "warning":
            messagebox.showwarning(title, message, parent=dialog)
        else:
            messagebox.showinfo(title, message, parent=dialog)
            
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (dialog.winfo_width() // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f'+{x}+{y}')
        dialog.destroy()
        
    def setup_ui(self, parent):
        # File selection
        file_frame = ttk.LabelFrame(parent, text="File Selection", padding="10")
        file_frame.pack(fill="x", pady=5)
        
        ttk.Button(file_frame, text="Select PVFS File", command=self.select_pvfs_file).pack(side="left", padx=5)
        self.file_label = ttk.Label(file_frame, text="No file selected")
        self.file_label.pack(side="left", padx=5)
        
        # Video channel selection
        channel_frame = ttk.LabelFrame(parent, text="Video Channel Selection", padding="10")
        channel_frame.pack(fill="both", expand=True, pady=5)
        
        self.channel_listbox = tk.Listbox(channel_frame, selectmode="single", 
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
        
        # Add time format help label
        ttk.Label(time_frame, text="Format: YYYY-MM-DD HH:MM:SS.ss", 
                 font=('TkDefaultFont', 9)).grid(row=1, column=0, columnspan=4, pady=5)
        
        # Output file selection
        output_frame = ttk.LabelFrame(parent, text="Output", padding="10")
        output_frame.pack(fill="x", pady=5)
        
        ttk.Button(output_frame, text="Select Output File", command=self.select_output_file).pack(side="left", padx=5)
        self.output_label = ttk.Label(output_frame, text="No output file selected")
        self.output_label.pack(side="left", padx=5)
        
        # Convert button
        convert_frame = ttk.Frame(parent)
        convert_frame.pack(fill="x", pady=10)
        ttk.Button(convert_frame, text="Convert to WebM", command=self.convert_to_webm).pack(pady=5)
        
        # Progress bar
        self.progress_frame = ttk.LabelFrame(parent, text="Progress", padding="10")
        self.progress_frame.pack(fill="x", pady=5)
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            self.progress_frame, 
            variable=self.progress_var,
            maximum=100,
            mode='determinate',
            length=300
        )
        self.progress_bar.pack(fill="x", padx=5, pady=5)
        
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
            
    def load_pvfs_file(self):
        db_path = None  # Initialize db_path before try block
        try:
            # Open PVFS file
            self.vfs = PvfsFile.open(self.pvfs_file)
            
            # Extract database
            db_path = os.path.join(os.path.dirname(self.pvfs_file), "temp.db3")
            result = self.vfs.extract("experiment.db3", db_path)
            if result != 0:
                raise Exception("Failed to extract database from PVFS file")
            
            self.db = ExperimentDatabase(db_path)
            
            # Get list of files in PVFS
            pvfs_files = self.vfs.get_file_list()
            
            # Get channel names from database
            channel_names = self.db.get_channel_names()
            
            # Clear the mapping
            self.channel_name_map.clear()
            self.channel_listbox.delete(0, tk.END)
            
            # Find video streams by looking for _frames and _index pairs
            video_streams = {}
            for filename in pvfs_files:
                if filename.endswith('_frames'):
                    base_name = filename[:-7]  # Remove '_frames' suffix
                    if f"{base_name}_index" in pvfs_files:
                        video_streams[base_name] = filename
            print(f"video_streams: {video_streams}")
            # Process each video stream
            for base_name, frames_file in video_streams.items():
                try:
                    # Try to open the video file to verify it's valid
                    with VideoDataFile(self.vfs, base_name) as video_file:
                        print(f"video_file: {video_file.is_valid()}")
                        if video_file.is_valid():
                            # Get frame rate from database if available
                            frame_rate = "Unknown"
                            for channel_name in channel_names:
                                channel_info = self.db.get_channel_info(channel_name)
                                print(f"channel_info: {channel_info}")
                                if channel_info and channel_info.filename == base_name:
                                    frame_rate = f"{channel_info.data_rate} fps"
                                    break
                            
                            # Add to listbox with frame rate
                            display_name = f"{base_name} ({frame_rate})"
                            self.channel_listbox.insert(tk.END, display_name)
                            self.channel_name_map[display_name] = base_name
                except Exception as e:
                    print(f"Warning: Could not read header for video stream {base_name}: {str(e)}")
                    continue
            
            # Select first channel by default if available
            if self.channel_listbox.size() > 0:
                self.channel_listbox.selection_set(0)
                
                # Get time range from the first video stream
                first_channel = self.channel_listbox.get(0)
                original_name = self.channel_name_map[first_channel]
                with VideoDataFile(self.vfs, original_name) as video_file:
                    start_time = video_file.get_start_time()
                    end_time = video_file.get_end_time()
                    
                    self.start_time_entry.delete(0, tk.END)
                    self.start_time_entry.insert(0, start_time.to_string_local())
                    
                    self.end_time_entry.delete(0, tk.END)
                    self.end_time_entry.insert(0, end_time.to_string_local())
            else:
                self.show_message("Warning", "No video streams found in PVFS file", "warning")
                
        except Exception as e:
            self.show_message("Error", f"Failed to load PVFS file: {str(e)}", "error")
            # Clean up temporary database file if it exists
            if db_path and os.path.exists(db_path):
                try:
                    os.remove(db_path)
                except:
                    pass
            
    def select_output_file(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension=".webm",
            filetypes=[("WebM files", "*.webm"), ("All files", "*.*")]
        )
        if file_path:
            self.output_file = file_path
            self.output_label.config(text=os.path.basename(file_path))
            
    def parse_local_time(self, time_str: str) -> float:
        """Parse a local time string into Unix timestamp."""
        try:
            dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S.%f')
            return dt.timestamp()
        except ValueError as e:
            raise ValueError(f"Invalid time format: {time_str}. Expected format: YYYY-MM-DD HH:MM:SS.ss")
            
    def update_progress(self, value: float, text: str = ""):
        """Update the progress bar and label."""
        if abs(self.progress_var.get() - value) > 1.0:
            self.progress_var.set(value)
            if text:
                self.progress_label.config(text=text)
            self.root.update_idletasks()
            
    def convert_to_webm(self):
        if not hasattr(self, 'output_file'):
            self.show_message("Error", "Please select an output file", "error")
            return
            
        try:
            # Reset progress
            self.update_progress(0, "Starting conversion...")
            
            # Get selected channel
            selected_indices = self.channel_listbox.curselection()
            if not selected_indices:
                self.show_message("Error", "Please select a video channel", "error")
                return
                
            selected_channel = self.channel_listbox.get(selected_indices[0])
            stream_name = self.channel_name_map[selected_channel]
            
            # Get time range
            try:
                start_time = self.parse_local_time(self.start_time_entry.get())
                end_time = self.parse_local_time(self.end_time_entry.get())
            except ValueError as e:
                self.show_message("Error", str(e), "error")
                return
                
            
            # Get the video data
            with VideoDataFile(self.vfs, stream_name) as video_file:
                start_ht = HighTime(start_time)
                end_ht = HighTime(end_time)
                width, height = video_file.get_frame_size()
                frame_rate = video_file.get_frame_rate()
                print(f"Frame  {width} {height} {frame_rate}")
                with WebMWriter("output.webm", frame_rate, width, height) as writer:                
                    start_index = 0
                    end_index = video_file.get_frame_count()
                    for i in range(start_index, end_index + 1):
                        ts, loc = video_file._read_frame_header(i)
                        frame = video_file._read_frame_data(loc)
                        is_key = video_file.check_vp8_header(frame) and (frame[0] & 0x01 == 0)
                        writer.write_frame(frame, is_keyframe=is_key)
                
        except Exception as e:
            error_msg = f"Conversion failed: {str(e)}"
            self.show_message("Error", error_msg, "error")
        finally:
            # Reset progress bar
            self.update_progress(0, "")
            
    def run(self):
        self.root.mainloop()
        
if __name__ == "__main__":
    app = PvfsToVideoConverter()
    app.run() 
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, scrolledtext
import json
import os
import sys
from pathlib import Path
import pygame
from pydub import AudioSegment
from pydub.exceptions import CouldntEncodeError
import subprocess
import threading
import queue
import time
import traceback

# --- Configuration ---
PATHS_FILENAME = 'paths.jsonl'
SCORES_FILENAME = 'scores.jsonl'
# --- End Configuration ---

# --- Helper Functions ---

def find_ffmpeg():
    """Checks if ffmpeg is likely available in PATH."""
    import shutil
    return shutil.which("ffmpeg") is not None

FFMPEG_AVAILABLE = find_ffmpeg()

def load_audio_data(base_dir):
    """
    Loads audio paths and scores from subdirectories of base_dir.
    Looks for paths.jsonl and scores.jsonl in each immediate subdirectory.
    """
    all_data = []
    if not base_dir or not os.path.isdir(base_dir):
        return [], "Selected path is not a valid directory.", 0

    print(f"Scanning directory: {base_dir}")
    found_files_flag = False
    subdirs_scanned = 0
    invalid_entries_count = 0

    for item in os.listdir(base_dir):
        subdir_path = os.path.join(base_dir, item)
        if os.path.isdir(subdir_path):
            subdirs_scanned += 1
            paths_file = os.path.join(subdir_path, PATHS_FILENAME)
            scores_file = os.path.join(subdir_path, SCORES_FILENAME)

            if os.path.exists(paths_file) and os.path.exists(scores_file):
                found_files_flag = True
                try:
                    paths_content = []
                    scores_content = []
                    # Read paths file line by line, handling potential errors
                    with open(paths_file, 'r', encoding='utf-8') as pf:
                         for line_num, line in enumerate(pf):
                             try:
                                 paths_content.append(json.loads(line))
                             except json.JSONDecodeError:
                                 print(f"    Warning: Skipping invalid JSON line {line_num+1} in {paths_file}: {line.strip()}")
                                 invalid_entries_count += 1
                    # Read scores file line by line
                    with open(scores_file, 'r', encoding='utf-8') as sf:
                         for line_num, line in enumerate(sf):
                             try:
                                 scores_content.append(json.loads(line))
                             except json.JSONDecodeError:
                                 print(f"    Warning: Skipping invalid JSON line {line_num+1} in {scores_file}: {line.strip()}")
                                 # Avoid double counting if both files have issues on same conceptual line
                                 # invalid_entries_count += 1

                    if len(paths_content) != len(scores_content):
                        print(f"    Warning: Mismatch in valid line count between {paths_file} ({len(paths_content)}) and {scores_file} ({len(scores_content)}). Skipping this subdirectory.")
                        continue

                    for path_data, score_data in zip(paths_content, scores_content):
                        full_path_str = path_data.get("path")
                        if not full_path_str:
                            print(f"    Warning: Missing 'path' key in {paths_file}. Skipping entry.")
                            invalid_entries_count += 1
                            continue

                        # Use Path object for robust handling
                        full_path = Path(full_path_str)

                        # Check if the file *actually* exists before adding
                        if not full_path.is_file():
                            print(f"    Warning: Path '{full_path_str}' from {paths_file} not found on disk. Skipping.")
                            invalid_entries_count += 1
                            continue

                        entry = {
                            'filename': full_path.name,
                            'path': str(full_path), # Store standard string path
                            'CE': score_data.get('CE', None),
                            'CU': score_data.get('CU', None),
                            'PC': score_data.get('PC', None),
                            'PQ': score_data.get('PQ', None),
                        }
                        all_data.append(entry)
                except Exception as e:
                    print(f"    Error processing subdirectory {item}: {e}\n{traceback.format_exc()}")
                    invalid_entries_count += 1 # Count errors during processing as invalid

    print(f"Scanned {subdirs_scanned} subdirectories.")
    if invalid_entries_count > 0:
        print(f"Encountered {invalid_entries_count} invalid/missing entries during loading.")

    if not found_files_flag and not all_data:
         return [], f"No subdirectories with '{PATHS_FILENAME}' and '{SCORES_FILENAME}' found or processed in {base_dir}.", subdirs_scanned
    elif not all_data and found_files_flag:
         return [], "Found subdirectories with jsonl files, but failed to load any valid audio entries (check paths and file existence).", subdirs_scanned

    print(f"Loaded {len(all_data)} audio entries.")
    return all_data, None, subdirs_scanned # Return data, no error message, count


def create_wav_jsonl(target_dir, output_filename="paths.jsonl", progress_callback=None):
    """
    Finds .wav files in target_dir and writes their absolute POSIX paths
    to output_filename in JSONL format. Ignores other file types (like .trn).

    Args:
        target_dir (str): Directory to search.
        output_filename (str): Output file name.
        progress_callback (callable, optional): Function to call for progress updates.
                                                 Expected signature: callback(processed_count, total_count, stage_message)

    Returns:
        tuple: (count, message) where count is number of WAVs found, or -1 on error.
    """
    wav_filenames = []
    all_files = []
    try:
        all_files = os.listdir(target_dir)
        wav_filenames = [f for f in all_files if f.lower().endswith('.wav')]
    except OSError as e:
         return -1, f"OSError listing files in {target_dir}: {e}"
    except Exception as e:
        return -1, f"Unexpected error listing files in {target_dir}: {e}"

    total_wavs = len(wav_filenames)
    output_path = os.path.join(target_dir, output_filename)
    count = 0

    if progress_callback:
        progress_callback(0, total_wavs, f"Scanning {total_wavs} WAVs...")

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            for i, wav_file in enumerate(wav_filenames):
                try:
                    # Get the absolute path relative to the filesystem root
                    full_path = os.path.abspath(os.path.join(target_dir, wav_file))
                    # Ensure cross-platform compatibility (forward slashes recommended)
                    full_path_posix = Path(full_path).as_posix()
                    entry = {"path": full_path_posix}
                    f.write(json.dumps(entry) + '\n')
                    count += 1
                except Exception as e_inner:
                    print(f"  Error processing file {wav_file}: {e_inner}", file=sys.stderr)
                    # Continue with other files

                # Report progress periodically
                if progress_callback and (i + 1) % 100 == 0: # Update every 100 files
                    progress_callback(i + 1, total_wavs, f"Writing paths.jsonl ({i+1}/{total_wavs})...")

        # Final update
        if progress_callback:
            progress_callback(count, total_wavs, f"Finished paths.jsonl ({count}/{total_wavs}).")

        # Check if count matches total_wavs, could indicate errors processing some files
        if count != total_wavs:
             print(f"  Warning: Found {total_wavs} WAV files but only wrote {count} paths to {output_filename}. Check for errors above.", file=sys.stderr)

        return count, f"Created {output_filename} with {count} WAV entries."

    except OSError as e:
        return -1, f"OSError creating {output_filename} in {target_dir}: {e}"
    except Exception as e:
        return -1, f"Unexpected error creating {output_filename} in {target_dir}: {e}\n{traceback.format_exc()}"


def run_audio_aes(target_dir, audio_aes_command, input_jsonl="paths.jsonl", output_jsonl="scores.jsonl", batch_size=100):
    """
    Runs the audio-aes command within the target_dir and returns success status
    and a detailed message including captured stdout/stderr.

    Args:
        target_dir (str): The directory where the command should be run and files exist.
        audio_aes_command (str): The name or path of the audio-aes executable.
        input_jsonl (str): The name of the input JSONL file (relative to target_dir).
        output_jsonl (str): The name of the output JSONL file (relative to target_dir).
        batch_size (int): The batch size for the audio-aes command.

    Returns:
        tuple: (success (bool), detailed_message (str))
    """
    input_path = os.path.join(target_dir, input_jsonl)
    output_path = os.path.join(target_dir, output_jsonl)

    if not os.path.exists(input_path):
        return False, f"Input file not found: {input_path}"
    try:
        if os.path.getsize(input_path) == 0:
             return False, f"Input file is empty: {input_path}"
    except OSError as e:
         return False, f"Error checking input file size {input_path}: {e}"

    command = [
        audio_aes_command,
        input_jsonl,
        '--batch-size',
        str(batch_size)
    ]
    cmd_str = ' '.join(command)
    print(f"  Running command in {target_dir}: {cmd_str}") # Console log

    try:
        process = subprocess.run(
            command,
            cwd=target_dir,
            capture_output=True,
            text=True,
            check=True, # Raise CalledProcessError on non-zero exit
            encoding='utf-8',
            errors='replace'
        )

        # Write captured stdout (scores) to the output file
        try:
            with open(output_path, 'w', encoding='utf-8') as f_out:
                f_out.write(process.stdout)
        except OSError as e:
             write_error_msg = f"ERROR writing output file {output_path}: {e}"
             # Include command output if available, but report failure
             combined_output = f"Command seemed to succeed but failed to write scores.jsonl: {e}\n"
             if process.stderr: combined_output += f"--- Command Stderr ---\n{process.stderr.strip()}\n"
             if process.stdout: combined_output += f"--- Command Stdout (Scores) ---\n{process.stdout.strip()}"
             return False, combined_output

        # Construct detailed success message including stdout/stderr
        msg = f"Command executed successfully. Output written to {output_jsonl}."
        # Append stderr first if it exists
        if process.stderr:
            msg += f"\n--- Command Standard Error ---\n{process.stderr.strip()}"
        # Append stdout (which includes scores, logs, progress)
        if process.stdout:
            msg += f"\n--- Command Standard Output ---\n{process.stdout.strip()}"

        return True, msg # Return success and the combined output message

    except FileNotFoundError:
        err_msg = f"ERROR: Command '{audio_aes_command}' not found. Make sure it's installed and in your system PATH."
        return False, err_msg
    except subprocess.CalledProcessError as e:
        # Construct detailed error message including captured output
        err_msg = f"ERROR running command. Exit code: {e.returncode}"
        # Include stderr and stdout for debugging
        if e.stderr:
            err_msg += f"\n--- Command Standard Error ---\n{e.stderr.strip()}"
        if e.stdout:
             err_msg += f"\n--- Command Standard Output (before error) ---\n{e.stdout.strip()}"
        return False, err_msg
    except OSError as e:
        err_msg = f"ERROR: OSError during command execution or writing output {output_path}: {e}"
        return False, err_msg
    except Exception as e:
        err_msg = f"ERROR: Unexpected error running {audio_aes_command}: {e}\n{traceback.format_exc()}"
        return False, err_msg


# --- GUI Application ---
class AudioReviewApp(tk.Tk):
    def __init__(self):
        print("DEBUG: Starting AudioReviewApp.__init__")
        super().__init__()
        self.title("Audio Review & Preprocessing Tool")
        self.geometry("1100x750")

        # Data storage
        self.full_audio_data = []
        self.display_audio_data = []

        # State variables
        self.current_sort_column = None
        self.current_sort_reverse = False
        self.selected_directory = tk.StringVar()
        self.audio_aes_command = tk.StringVar(value='audio-aes')
        self.audio_aes_batch_size = tk.IntVar(value=10) # <<< Set safer default batch size
        self.preprocess_overwrite = tk.BooleanVar(value=False)

        # Threading communication and control
        self.task_queue = queue.Queue()
        self.preprocessing_thread = None # <<< Reference to the background thread
        self.stop_event = threading.Event() # <<< Event to signal stop
        self.after(100, self.process_queue)

        print("DEBUG: Initializing Pygame mixer...")
        self.playback_enabled = False
        try:
            pygame.mixer.init()
            self.playback_enabled = True
            print("Pygame mixer initialized successfully.")
        except pygame.error as e:
            messagebox.showwarning("Playback Warning", f"Could not initialize audio playback: {e}\nPlayback will be disabled.")
            print(f"Pygame mixer init error: {e}")

        print("DEBUG: Calling _create_widgets...")
        self._create_widgets()
        print("DEBUG: Finished _create_widgets.")

        print("DEBUG: Setting up protocol handler...")
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        print("DEBUG: Finished AudioReviewApp.__init__")


    def process_queue(self):
        """ Process tasks from the background thread queue to update GUI safely. """
        try:
            while True:
                task = self.task_queue.get_nowait()
                if task:
                    func, args = task
                    func(*args)
                self.task_queue.task_done()
        except queue.Empty:
            pass
        finally:
            self.after(100, self.process_queue)

    def _update_status(self, message):
        """ Safely update status bar text from any thread via the queue. """
        self.task_queue.put((self.status_label.config, ({'text': f"Status: {message}"},)))
        print(f"Status Update: {message}")

    def _append_log(self, message):
        """ Safely append message to the log ScrolledText widget from any thread. """
        if hasattr(self, 'log_text') and self.log_text:
            self.task_queue.put((self._do_append_log, (message,)))

    def _do_append_log(self, message):
         """ Actual log update method (must run in main GUI thread). """
         try:
             self.log_text.config(state=tk.NORMAL)
             self.log_text.insert(tk.END, message + '\n')
             self.log_text.see(tk.END)
             self.log_text.config(state=tk.DISABLED)
         except tk.TclError as e:
              print(f"Error appending to log (widget might be destroyed): {e}")

    def _update_preprocess_status(self, current, total, message):
        """ Specific status update for preprocessing progress. """
        status_text = f"Status: {message}"
        self.task_queue.put((self.status_label.config, ({'text': status_text},)))

    def _create_widgets(self):
        # --- Top Frame: Directory Selection & Preprocessing ---
        top_frame = ttk.Frame(self, padding="10")
        top_frame.pack(fill=tk.X)

        ttk.Label(top_frame, text="Dataset Dir:").pack(side=tk.LEFT, padx=(0, 5))
        dir_entry = ttk.Entry(top_frame, textvariable=self.selected_directory, width=40)
        dir_entry.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        browse_button = ttk.Button(top_frame, text="Browse...", command=self.browse_directory)
        browse_button.pack(side=tk.LEFT, padx=5)
        load_button = ttk.Button(top_frame, text="Load Data", command=self.load_and_display_data)
        load_button.pack(side=tk.LEFT, padx=5)
        preprocess_button = ttk.Button(top_frame, text="Preprocess Options...", command=self.run_preprocessing_thread)
        preprocess_button.pack(side=tk.LEFT, padx=5)

        # --- Filter Frame ---
        filter_frame = ttk.LabelFrame(self, text="Filters", padding="10")
        filter_frame.pack(fill=tk.X, padx=10, pady=5)
        filter_frame.columnconfigure(1, weight=1); filter_frame.columnconfigure(3, weight=1)
        filter_frame.columnconfigure(5, weight=1); filter_frame.columnconfigure(7, weight=1)

        ttk.Label(filter_frame, text="Filename contains:").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.filter_filename = ttk.Entry(filter_frame, width=25); self.filter_filename.grid(row=0, column=1, padx=5, pady=2, sticky="ew")
        ttk.Label(filter_frame, text="PQ >=").grid(row=0, column=2, padx=(15, 5), pady=2, sticky="w")
        self.filter_pq_min = ttk.Entry(filter_frame, width=8); self.filter_pq_min.grid(row=0, column=3, padx=5, pady=2, sticky="ew")
        ttk.Label(filter_frame, text="PQ <=").grid(row=0, column=4, padx=5, pady=2, sticky="w")
        self.filter_pq_max = ttk.Entry(filter_frame, width=8); self.filter_pq_max.grid(row=0, column=5, padx=5, pady=2, sticky="ew")
        ttk.Label(filter_frame, text="CE >=").grid(row=1, column=2, padx=(15, 5), pady=2, sticky="w")
        self.filter_ce_min = ttk.Entry(filter_frame, width=8); self.filter_ce_min.grid(row=1, column=3, padx=5, pady=2, sticky="ew")
        ttk.Label(filter_frame, text="CE <=").grid(row=1, column=4, padx=5, pady=2, sticky="w")
        self.filter_ce_max = ttk.Entry(filter_frame, width=8); self.filter_ce_max.grid(row=1, column=5, padx=5, pady=2, sticky="ew")
        ttk.Label(filter_frame, text="CU >=").grid(row=1, column=6, padx=(15, 5), pady=2, sticky="w")
        self.filter_cu_min = ttk.Entry(filter_frame, width=8); self.filter_cu_min.grid(row=1, column=7, padx=5, pady=2, sticky="ew")
        ttk.Label(filter_frame, text="CU <=").grid(row=1, column=8, padx=5, pady=2, sticky="w")
        self.filter_cu_max = ttk.Entry(filter_frame, width=8); self.filter_cu_max.grid(row=1, column=9, padx=5, pady=2, sticky="ew")
        ttk.Label(filter_frame, text="PC >=").grid(row=2, column=2, padx=(15, 5), pady=2, sticky="w")
        self.filter_pc_min = ttk.Entry(filter_frame, width=8); self.filter_pc_min.grid(row=2, column=3, padx=5, pady=2, sticky="ew")
        ttk.Label(filter_frame, text="PC <=").grid(row=2, column=4, padx=5, pady=2, sticky="w")
        self.filter_pc_max = ttk.Entry(filter_frame, width=8); self.filter_pc_max.grid(row=2, column=5, padx=5, pady=2, sticky="ew")
        filter_button_frame = ttk.Frame(filter_frame); filter_button_frame.grid(row=2, column=6, columnspan=4, pady=5, sticky="e")
        filter_button = ttk.Button(filter_button_frame, text="Apply Filters", command=self.apply_filters); filter_button.pack(side=tk.LEFT, padx=(15, 5))
        clear_filter_button = ttk.Button(filter_button_frame, text="Clear Filters", command=self.clear_filters); clear_filter_button.pack(side=tk.LEFT, padx=5)

        # --- Middle Frame: Treeview (Data Table) ---
        tree_frame = ttk.Frame(self, padding=(10, 0, 10, 0))
        tree_frame.pack(expand=True, fill=tk.BOTH, pady=5)
        self.tree = ttk.Treeview(tree_frame, columns=('Filename', 'CE', 'CU', 'PC', 'PQ', 'Path'), show='headings', selectmode='extended')
        self.tree.heading('Filename', text='Filename', anchor=tk.W, command=lambda: self.sort_column('filename'))
        self.tree.column('Filename', anchor=tk.W, width=350, stretch=tk.YES)
        self.tree.heading('CE', text='CE', anchor=tk.E, command=lambda: self.sort_column('CE', True))
        self.tree.column('CE', anchor=tk.E, width=80, stretch=tk.NO)
        self.tree.heading('CU', text='CU', anchor=tk.E, command=lambda: self.sort_column('CU', True))
        self.tree.column('CU', anchor=tk.E, width=80, stretch=tk.NO)
        self.tree.heading('PC', text='PC', anchor=tk.E, command=lambda: self.sort_column('PC', True))
        self.tree.column('PC', anchor=tk.E, width=80, stretch=tk.NO)
        self.tree.heading('PQ', text='PQ', anchor=tk.E, command=lambda: self.sort_column('PQ', True))
        self.tree.column('PQ', anchor=tk.E, width=80, stretch=tk.NO)
        self.tree.heading('Path', text='Full Path', anchor=tk.W, command=lambda: self.sort_column('path'))
        self.tree.column('Path', anchor=tk.W, width=300, stretch=tk.YES)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y); hsb.pack(side=tk.BOTTOM, fill=tk.X); self.tree.pack(expand=True, fill=tk.BOTH)
        self.tree.bind('<Double-1>', self.play_selected); self.tree.bind('<<TreeviewSelect>>', self.update_selection_count)

        # --- Action Frame (Below Treeview) ---
        action_frame = ttk.Frame(self, padding="5"); action_frame.pack(fill=tk.X)
        select_all_button = ttk.Button(action_frame, text="Select All Visible", command=self.select_all_visible); select_all_button.pack(side=tk.LEFT, padx=5)
        deselect_all_button = ttk.Button(action_frame, text="Deselect All", command=self.deselect_all); deselect_all_button.pack(side=tk.LEFT, padx=5)
        play_button = ttk.Button(action_frame, text="Play Selected", command=self.play_selected, state=tk.DISABLED if not self.playback_enabled else tk.NORMAL); play_button.pack(side=tk.LEFT, padx=(20, 5))
        export_audio_button = ttk.Button(action_frame, text="Export Selected Audio...", command=self.export_selected_audio); export_audio_button.pack(side=tk.LEFT, padx=5)
        export_list_button = ttk.Button(action_frame, text="Export Selected File List...", command=self.export_selected_list); export_list_button.pack(side=tk.LEFT, padx=5)
        self.visible_count_label = ttk.Label(action_frame, text="Visible: 0"); self.visible_count_label.pack(side=tk.RIGHT, padx=10)
        self.selected_count_label = ttk.Label(action_frame, text="Selected: 0"); self.selected_count_label.pack(side=tk.RIGHT, padx=10)

        # --- Log Frame ---
        log_frame = ttk.LabelFrame(self, text="Log / Preprocessing Output", padding="5"); log_frame.pack(fill=tk.BOTH, expand=False, padx=10, pady=(5,0))
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, wrap=tk.WORD, state=tk.DISABLED); self.log_text.pack(expand=True, fill=tk.BOTH)

        # --- Bottom Frame: Status Bar ---
        status_frame = ttk.Frame(self, relief=tk.SUNKEN, padding="2"); status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_label = ttk.Label(status_frame, text="Status: Ready. Select a directory and load data."); self.status_label.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)


    def browse_directory(self):
        """ Opens a dialog to select the main dataset directory. """
        directory = filedialog.askdirectory(title="Select Main Dataset Directory (Containing Subdirs)")
        if directory:
            self.selected_directory.set(directory)
            self._update_status(f"Selected directory: {directory}. Click 'Load Data' or 'Preprocess Options...'.")
            self.full_audio_data = []
            self.display_audio_data = []
            self.clear_treeview()
            self.update_counts()

    def load_and_display_data(self):
        """ Loads data from JSONL files in subdirs and displays it. """
        directory = self.selected_directory.get()
        if not directory:
            messagebox.showwarning("No Directory", "Please select a directory first using 'Browse...'.")
            return

        self._update_status("Loading data...")
        self.update_idletasks()

        self.full_audio_data = []
        self.display_audio_data = []
        self.clear_treeview()
        self.update_counts()

        start_time = time.time()
        try:
            loaded_data, error_msg, subdir_count = load_audio_data(directory)
            load_time = time.time() - start_time

            if loaded_data and len(loaded_data) > 100000:
                messagebox.showwarning("Large Dataset Loaded",
                                       f"Loaded {len(loaded_data)} audio file entries.\n\n"
                                       "Displaying and sorting this many files directly may be slow or unstable.\n\n"
                                       "It is strongly recommended to use the filter options to significantly reduce the number of visible items before interacting heavily with the table.",
                                       parent=self)

            if error_msg:
                messagebox.showerror("Loading Error", error_msg)
                self._update_status(f"Error loading: {error_msg}")
            elif not loaded_data:
                messagebox.showinfo("No Data", f"No audio data found or loaded from the {subdir_count} scanned subdirectories.")
                self._update_status(f"Scanned {subdir_count} subdirs. No data loaded. Load time: {load_time:.2f}s")
            else:
                self.full_audio_data = loaded_data
                self.apply_filters()
                self._update_status(f"Loaded {len(self.full_audio_data)} files from {subdir_count} subdirs. Load time: {load_time:.2f}s. Use filters for large datasets.")
        except Exception as e:
            load_time = time.time() - start_time
            self._update_status(f"Critical error during loading after {load_time:.2f}s.")
            messagebox.showerror("Loading Failed", f"An unexpected error occurred during data loading:\n{e}\n\n{traceback.format_exc()}")
            print(f"CRITICAL LOADING ERROR: {e}\n{traceback.format_exc()}")

    def _parse_filter_value(self, value_str):
        """ Helper to parse float filter values, returns None if invalid/empty. """
        if not value_str.strip(): return None
        try: return float(value_str)
        except ValueError: return None

    def apply_filters(self):
        """ Filters self.full_audio_data into self.display_audio_data based on GUI filter criteria and updates Treeview. """
        self._update_status("Applying filters...")
        self.update_idletasks()

        filter_filename_str = self.filter_filename.get().lower().strip()
        pq_min = self._parse_filter_value(self.filter_pq_min.get()); pq_max = self._parse_filter_value(self.filter_pq_max.get())
        ce_min = self._parse_filter_value(self.filter_ce_min.get()); ce_max = self._parse_filter_value(self.filter_ce_max.get())
        cu_min = self._parse_filter_value(self.filter_cu_min.get()); cu_max = self._parse_filter_value(self.filter_cu_max.get())
        pc_min = self._parse_filter_value(self.filter_pc_min.get()); pc_max = self._parse_filter_value(self.filter_pc_max.get())

        if pq_min is not None and pq_max is not None and pq_min > pq_max: messagebox.showwarning("Filter Warning", "PQ min value is greater than max value.", parent=self); return
        if ce_min is not None and ce_max is not None and ce_min > ce_max: messagebox.showwarning("Filter Warning", "CE min value is greater than max value.", parent=self); return
        if cu_min is not None and cu_max is not None and cu_min > cu_max: messagebox.showwarning("Filter Warning", "CU min value is greater than max value.", parent=self); return
        if pc_min is not None and pc_max is not None and pc_min > pc_max: messagebox.showwarning("Filter Warning", "PC min value is greater than max value.", parent=self); return

        filter_start_time = time.time()
        filtered_data = []
        try:
            for entry in self.full_audio_data:
                if filter_filename_str and filter_filename_str not in entry['filename'].lower(): continue
                if pq_min is not None and (entry['PQ'] is None or entry['PQ'] < pq_min): continue
                if pq_max is not None and (entry['PQ'] is None or entry['PQ'] > pq_max): continue
                if ce_min is not None and (entry['CE'] is None or entry['CE'] < ce_min): continue
                if ce_max is not None and (entry['CE'] is None or entry['CE'] > ce_max): continue
                if cu_min is not None and (entry['CU'] is None or entry['CU'] < cu_min): continue
                if cu_max is not None and (entry['CU'] is None or entry['CU'] > cu_max): continue
                if pc_min is not None and (entry['PC'] is None or entry['PC'] < pc_min): continue
                if pc_max is not None and (entry['PC'] is None or entry['PC'] > pc_max): continue
                filtered_data.append(entry)

            self.display_audio_data = filtered_data
            filter_time = time.time() - filter_start_time
            print(f"Filtering took {filter_time:.3f}s")

            self.current_sort_column = None; self.current_sort_reverse = False
            self.populate_treeview()
            self._update_status(f"Filters applied. Displaying {len(self.display_audio_data)} out of {len(self.full_audio_data)} files.")

        except Exception as e:
            self._update_status("Error applying filters.")
            messagebox.showerror("Filter Error", f"An unexpected error occurred during filtering:\n{e}\n\n{traceback.format_exc()}")
            print(f"FILTERING ERROR: {e}\n{traceback.format_exc()}")


    def clear_filters(self):
        """ Clears filter entry fields and reapplies (showing all data or respecting previous full load). """
        self.filter_filename.delete(0, tk.END)
        self.filter_pq_min.delete(0, tk.END); self.filter_pq_max.delete(0, tk.END)
        self.filter_ce_min.delete(0, tk.END); self.filter_ce_max.delete(0, tk.END)
        self.filter_cu_min.delete(0, tk.END); self.filter_cu_max.delete(0, tk.END)
        self.filter_pc_min.delete(0, tk.END); self.filter_pc_max.delete(0, tk.END)
        self.apply_filters()

    def clear_treeview(self):
        """ Removes all items from the Treeview widget. """
        if self.tree.get_children():
            try:
                self.tree.delete(*self.tree.get_children())
            except tk.TclError as e:
                 print(f"Ignoring error during Treeview clear (possibly already destroyed): {e}")


    def populate_treeview(self):
        """ Populates the treeview with data from self.display_audio_data. """
        self.clear_treeview()
        insert_start_time = time.time()
        try:
            items_to_insert = []
            for entry in self.display_audio_data:
                ce_val = f"{entry['CE']:.4f}" if entry['CE'] is not None else "N/A"
                cu_val = f"{entry['CU']:.4f}" if entry['CU'] is not None else "N/A"
                pc_val = f"{entry['PC']:.4f}" if entry['PC'] is not None else "N/A"
                pq_val = f"{entry['PQ']:.4f}" if entry['PQ'] is not None else "N/A"
                items_to_insert.append(
                    ('', tk.END, entry['path'], {'values': (entry['filename'], ce_val, cu_val, pc_val, pq_val, entry['path'])})
                 )

            for parent, index, iid, options in items_to_insert:
                 try:
                     self.tree.insert(parent, index, iid=iid, **options)
                 except tk.TclError as e:
                     # Handle cases where an item might already exist if logic allows duplicates (it shouldn't with path as iid)
                     print(f"Warning: Could not insert item with iid '{iid}' into Treeview: {e}")
                     continue # Skip this item

            insert_time = time.time() - insert_start_time
            print(f"Populating Treeview with {len(self.display_audio_data)} items took {insert_time:.3f}s")
            if insert_time > 2.0:
                 print("Warning: Treeview population is slow. Consider applying stricter filters.")
                 self._update_status(f"Displaying {len(self.display_audio_data)} items (Warning: Render may be slow).")

        except Exception as e:
             self._update_status("Error populating table.")
             messagebox.showerror("Display Error", f"An error occurred displaying the data:\n{e}\n\n{traceback.format_exc()}")
             print(f"POPULATE TREEVIEW ERROR: {e}\n{traceback.format_exc()}")
        finally:
            self.update_counts()

    def get_entry_by_iid(self, iid):
        """ Finds the original data dictionary from self.full_audio_data using the Treeview item ID (path). """
        for entry in self.full_audio_data:
            if entry['path'] == iid: return entry
        return None

    def sort_column(self, col_key, is_numeric=False):
        """ Sorts the *displayed* data (self.display_audio_data) and repopulates the treeview. """
        if not self.display_audio_data: self._update_status("Nothing to sort."); return

        self._update_status(f"Sorting by {col_key}...")
        self.update_idletasks()

        reverse = False
        if self.current_sort_column == col_key: reverse = not self.current_sort_reverse
        else: reverse = False

        def sort_key(item):
            val = item.get(col_key)
            if val is None: return float('inf') if not reverse else float('-inf')
            if is_numeric:
                try: return float(val)
                except (ValueError, TypeError): return float('inf') if not reverse else float('-inf')
            return str(val).lower()

        sort_start_time = time.time()
        try:
            self.display_audio_data.sort(key=sort_key, reverse=reverse)
            self.current_sort_column = col_key
            self.current_sort_reverse = reverse
            sort_time = time.time() - sort_start_time
            print(f"Sorting {len(self.display_audio_data)} items took {sort_time:.3f}s")

            self.populate_treeview()
            self._update_status(f"Sorted by {col_key} {'descending' if reverse else 'ascending'}.")
        except Exception as e:
            self._update_status("Error during sorting.")
            messagebox.showerror("Sort Error", f"Could not sort column '{col_key}': {e}\n\n{traceback.format_exc()}")
            print(f"SORTING ERROR: {e}\n{traceback.format_exc()}")


    def update_counts(self):
        """ Updates the visible and selected count labels at the bottom. """
        try:
            visible_count = len(self.tree.get_children())
            selected_count = len(self.tree.selection())
            self.visible_count_label.config(text=f"Visible: {visible_count}")
            self.selected_count_label.config(text=f"Selected: {selected_count}")
        except tk.TclError:
             pass # Ignore errors if widgets are being destroyed

    def update_selection_count(self, event=None):
         """ Callback for Treeview selection change event. """
         self.update_counts()

    def select_all_visible(self):
        """ Selects all items currently visible in the treeview. """
        self._update_status("Selecting all visible items...")
        try:
            all_items = self.tree.get_children()
            if all_items:
                self.tree.selection_set(all_items)
            self.update_counts()
            self._update_status(f"Selected {len(all_items)} visible items.")
        except Exception as e:
             self._update_status("Error selecting all items.")
             print(f"SELECT ALL ERROR: {e}\n{traceback.format_exc()}")

    def deselect_all(self):
        """ Deselects all items in the treeview. """
        if self.tree.selection():
            self.tree.selection_set([])
            self.update_counts()
            self._update_status("Selection cleared.")

    def play_selected(self, event=None):
        """ Plays the first selected audio file using pygame. """
        if not self.playback_enabled: self._update_status("Playback disabled (mixer init failed)."); return

        selected_items = self.tree.selection()
        if not selected_items: self._update_status("Select a file to play."); return
        if len(selected_items) > 1: self._update_status("Multiple files selected. Playing the first one.")

        item_id = selected_items[0]
        entry = self.get_entry_by_iid(item_id)

        if not entry: self._update_status(f"Error finding data for selected item: {item_id}"); print(f"Error: Could not find data dictionary for tree item iid: {item_id}"); return

        file_path = entry['path']; display_name = entry['filename']

        if not os.path.exists(file_path):
            self._update_status(f"Error - File not found: {display_name}")
            messagebox.showerror("File Not Found", f"The audio file could not be found at the expected path:\n{file_path}", parent=self)
            return

        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            self._update_status(f"Playing: {display_name}")
        except pygame.error as e:
            self._update_status(f"Error playing {display_name}: {e}")
            messagebox.showerror("Playback Error", f"Could not play file:\n{file_path}\n\nPygame Error: {e}", parent=self)
            print(f"Error playing {file_path}: {e}")
        except Exception as e:
             self._update_status(f"Unexpected error playing {display_name}")
             messagebox.showerror("Playback Error", f"An unexpected error occurred during playback attempt:\n{e}\n\n{traceback.format_exc()}", parent=self)
             print(f"Unexpected error playing {file_path}: {e}\n{traceback.format_exc()}")


    def export_selected_audio(self):
        """ Exports selected files as a single concatenated audio file (WAV or MP3). Runs in background thread. """
        selected_iids = self.tree.selection()
        if not selected_iids: messagebox.showinfo("No Selection", "Please select one or more audio files to export.", parent=self); return

        file_types = [("WAV files", "*.wav")]; default_ext = ".wav"
        if FFMPEG_AVAILABLE: file_types.append(("MP3 files", "*.mp3"))
        else: print("FFmpeg not detected, MP3 export option disabled.")

        output_path = filedialog.asksaveasfilename(title="Export Combined Audio As", defaultextension=default_ext, filetypes=file_types, parent=self)
        if not output_path: return

        output_format = Path(output_path).suffix[1:].lower()
        if output_format == "mp3" and not FFMPEG_AVAILABLE: messagebox.showerror("Export Error", "Cannot export as MP3 because FFmpeg was not found or is not in the system PATH.", parent=self); return

        self._update_status(f"Starting export of {len(selected_iids)} files as '{output_format}'...")
        self.update_idletasks()
        print(f"Starting background export of {len(selected_iids)} files to {output_path} (format: {output_format})")

        thread = threading.Thread(target=self._perform_audio_export, args=(list(selected_iids), output_path, output_format), daemon=True)
        thread.start()

    def _perform_audio_export(self, selected_iids, output_path, output_format):
        """ Actual audio export logic (concatenation and saving). Runs in background thread. """
        combined_audio = None; exported_count = 0; error_files = []
        start_time = time.time()

        ordered_selection_paths = [item for item in self.tree.get_children() if item in selected_iids]
        total_to_export = len(ordered_selection_paths)
        self._append_log(f"Preparing to export {total_to_export} selected files...")

        for i, file_path in enumerate(ordered_selection_paths):
            self._update_status(f"Exporting audio... Processing file {i+1}/{total_to_export}")
            entry = self.get_entry_by_iid(file_path); filename = Path(file_path).name if not entry else entry['filename']
            self._append_log(f"  [{i+1}/{total_to_export}] Adding: {filename}")

            if not os.path.exists(file_path): self._append_log(f"    Error: File not found - {file_path}"); error_files.append(filename + " (Not Found)"); continue

            try:
                audio_segment = AudioSegment.from_wav(file_path)
                if combined_audio is None: combined_audio = audio_segment
                else: combined_audio += audio_segment
                exported_count += 1
            except FileNotFoundError: self._append_log(f"    Error: File not found during pydub load - {filename}"); error_files.append(f"{filename} (Not Found)")
            except Exception as e: self._append_log(f"    Error loading/processing {filename}: {type(e).__name__} - {e}"); error_files.append(f"{filename} ({type(e).__name__})")

        if combined_audio is None:
            self._update_status("Export failed - no valid audio files could be processed.")
            self._append_log("Export cancelled: No valid audio segments were loaded.")
            self.task_queue.put((messagebox.showerror, ("Export Failed", "No valid audio files could be processed for export.", {'parent': self})))
            return

        try:
            self._append_log(f"Finalizing export... Saving combined audio to {output_path}")
            self._update_status(f"Saving combined audio to {Path(output_path).name}...")
            combined_audio.export(output_path, format=output_format)
            export_time = time.time() - start_time
            self._update_status(f"Successfully exported {exported_count} files to {Path(output_path).name} in {export_time:.2f}s.")
            self._append_log(f"Successfully exported {exported_count} combined files in {export_time:.2f}s.")

            final_message = f"Successfully exported {exported_count} combined audio files to:\n{output_path}"
            if error_files:
                 final_message += "\n\nThe following files encountered errors and were skipped:\n - " + "\n - ".join(error_files)
                 self.task_queue.put((messagebox.showwarning, ("Export Complete with Errors", final_message, {'parent': self})))
            else:
                 self.task_queue.put((messagebox.showinfo, ("Export Complete", final_message, {'parent': self})))

        except CouldntEncodeError as e:
             err_msg = f"Could not encode the audio file (format: {output_format}).\nEnsure FFmpeg is installed correctly and accessible in your system's PATH for non-WAV export.\n\nPydub Error: {e}"
             self._update_status("Export error (encoding). Check log.")
             self._append_log(f"Export Encoding Error: {err_msg}\n{traceback.format_exc()}")
             self.task_queue.put((messagebox.showerror, ("Export Error", err_msg, {'parent': self})))
        except Exception as e:
             err_msg = f"An unexpected error occurred during the final export save step:\n{e}"
             self._update_status("Export error (saving). Check log.")
             self._append_log(f"Unexpected Export Error: {err_msg}\n{traceback.format_exc()}")
             self.task_queue.put((messagebox.showerror, ("Export Error", err_msg, {'parent': self})))

    def export_selected_list(self):
        """ Exports the full paths of selected files to a text file (txt or jsonl). """
        selected_iids = self.tree.selection()
        if not selected_iids: messagebox.showinfo("No Selection", "Please select one or more files to export their paths.", parent=self); return

        output_path = filedialog.asksaveasfilename(title="Export Selected File List As", defaultextension=".txt", filetypes=[("Text files", "*.txt"), ("JSONL files", "*.jsonl"), ("All files", "*.*")], parent=self)
        if not output_path: return

        ordered_selection_paths = [item for item in self.tree.get_children() if item in selected_iids]
        count_to_export = len(ordered_selection_paths)

        self._update_status(f"Exporting {count_to_export} file paths...")
        try:
            count = 0
            with open(output_path, 'w', encoding='utf-8') as f:
                if output_path.lower().endswith(".jsonl"):
                     for file_path in ordered_selection_paths: f.write(json.dumps({"path": file_path}) + '\n'); count += 1
                else:
                     for file_path in ordered_selection_paths: f.write(file_path + '\n'); count += 1

            self._update_status(f"Successfully exported {count} file paths to {Path(output_path).name}.")
            messagebox.showinfo("Export Complete", f"Successfully exported {count} file paths to:\n{output_path}", parent=self)

        except Exception as e:
             self._update_status("Error exporting file list.")
             messagebox.showerror("Export Error", f"Could not write the file list:\n{e}\n\n{traceback.format_exc()}", parent=self)
             print(f"Error exporting file list: {e}\n{traceback.format_exc()}")


    def run_preprocessing_thread(self):
        """ Opens options dialog and starts the preprocessing job in a background thread. """
        base_dir = self.selected_directory.get()
        if not base_dir or not os.path.isdir(base_dir): messagebox.showerror("Invalid Directory", "Please select a valid base directory containing the subdirectories to process.", parent=self); return

        # <<< Check if a thread is already running >>>
        if self.preprocessing_thread and self.preprocessing_thread.is_alive():
             messagebox.showwarning("Preprocessing Busy", "A preprocessing job is already running. Please wait for it to complete or close the application and restart if it's stuck.", parent=self)
             return

        # --- Create options dialog ---
        dialog = tk.Toplevel(self); dialog.title("Preprocessing Options"); dialog.transient(self); dialog.grab_set(); dialog.resizable(False, False)
        self.update_idletasks(); x = self.winfo_rootx() + (self.winfo_width() // 2) - (dialog.winfo_reqwidth() // 2); y = self.winfo_rooty() + (self.winfo_height() // 3) - (dialog.winfo_reqheight() // 2); dialog.geometry(f"+{x}+{y}")
        main_frame = ttk.Frame(dialog, padding="15"); main_frame.pack(expand=True, fill="both")
        ttk.Label(main_frame, text="Audio-AES Command:").grid(row=0, column=0, padx=5, pady=5, sticky="w"); cmd_entry = ttk.Entry(main_frame, textvariable=self.audio_aes_command, width=40); cmd_entry.grid(row=0, column=1, columnspan=2, padx=5, pady=5, sticky="ew")
        ttk.Label(main_frame, text="Batch Size:").grid(row=1, column=0, padx=5, pady=5, sticky="w"); batch_entry = ttk.Entry(main_frame, textvariable=self.audio_aes_batch_size, width=10); batch_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        overwrite_check = ttk.Checkbutton(main_frame, text="Overwrite existing scores.jsonl files", variable=self.preprocess_overwrite, onvalue=True, offvalue=False); overwrite_check.grid(row=2, column=0, columnspan=3, padx=5, pady=10, sticky="w")
        button_frame = ttk.Frame(main_frame); button_frame.grid(row=3, column=0, columnspan=3, pady=(10,0))
        result = {"ok_clicked": False}
        def on_ok():
            aes_cmd = self.audio_aes_command.get().strip()
            if not aes_cmd: messagebox.showerror("Invalid Input", "Please enter the audio-aes command or path.", parent=dialog); return
            try:
                bs = int(self.audio_aes_batch_size.get())
                if bs < 1: raise ValueError("Batch size must be a positive integer.")
                result["aes_cmd"] = aes_cmd; result["batch_size"] = bs; result["overwrite"] = self.preprocess_overwrite.get()
                result["ok_clicked"] = True; dialog.destroy()
            except ValueError as e: messagebox.showerror("Invalid Input", f"Please enter a valid positive integer for Batch Size.\nError: {e}", parent=dialog)
        def on_cancel(): dialog.destroy()
        ok_button = ttk.Button(button_frame, text="Start Preprocessing", command=on_ok); ok_button.pack(side="left", padx=10)
        cancel_button = ttk.Button(button_frame, text="Cancel", command=on_cancel); cancel_button.pack(side="left", padx=10)
        dialog.wait_window()
        # --- End of dialog ---

        if not result["ok_clicked"]: self._update_status("Preprocessing cancelled by user."); return

        self.log_text.config(state=tk.NORMAL); self.log_text.delete('1.0', tk.END); self.log_text.config(state=tk.DISABLED)
        self._update_status("Starting preprocessing job...")
        self._append_log(f"--- Starting New Preprocessing Job ---")
        self._append_log(f"Base Directory: {base_dir}")
        self._append_log(f"Audio-AES Command: {result['aes_cmd']}")
        self._append_log(f"Batch Size: {result['batch_size']}")
        self._append_log(f"Overwrite Existing scores.jsonl: {result['overwrite']}")
        self._append_log("--------------------------------------")

        # <<< Create and start the thread, storing reference >>>
        self.stop_event.clear() # Ensure stop is cleared for the new job
        self.preprocessing_thread = threading.Thread(target=self._perform_preprocessing,
                                                     args=(base_dir, result['aes_cmd'], result['batch_size'], result['overwrite']),
                                                     daemon=True)
        self.preprocessing_thread.start()

    def _perform_preprocessing(self, base_dir, audio_aes_cmd, batch_size, overwrite_existing):
        """ The actual preprocessing logic (runs in background thread). Checks stop_event. """
        start_time = time.time()
        processed_count = 0; error_count = 0; skipped_no_wav_count = 0; skipped_existing_count = 0
        subdirs_found = []

        # Reset stop event at the start of the task itself too (belt-and-suspenders)
        # self.stop_event.clear() # Already cleared before starting thread

        try:
            subdirs_found = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
            subdirs_found.sort()
        except OSError as e:
            self._append_log(f"FATAL ERROR: Could not list directories in {base_dir}: {e}")
            self._update_status("Preprocessing failed: Could not list subdirectories.")
            self.task_queue.put((messagebox.showerror, ("Preprocessing Error", f"Could not list subdirectories in {base_dir}:\n{e}", {'parent': self})))
            self.preprocessing_thread = None # Clear thread ref on error
            return

        if not subdirs_found:
            self._append_log("No subdirectories found to process in the selected base directory.")
            self._update_status("Preprocessing finished: No subdirectories found.")
            self.preprocessing_thread = None # Clear thread ref
            return

        total_dirs = len(subdirs_found)
        self._append_log(f"Found {total_dirs} subdirectories. Starting processing...")

        # --- Loop through directories ---
        for i, subdir_name in enumerate(subdirs_found):

            # <<< Check stop event at start of loop iteration >>>
            if self.stop_event.is_set():
                self._append_log(f"Stop requested. Halting preprocessing before processing '{subdir_name}'.")
                break

            current_subdir_path = os.path.join(base_dir, subdir_name)
            progress_prefix = f"({i+1}/{total_dirs}) {subdir_name}:"
            self._update_status(f"{progress_prefix} Starting..."); self._append_log(f"\n--- {progress_prefix} ---")

            paths_jsonl_path = os.path.join(current_subdir_path, PATHS_FILENAME)
            scores_jsonl_path = os.path.join(current_subdir_path, SCORES_FILENAME)

            # Check skip condition
            if not overwrite_existing and os.path.exists(scores_jsonl_path):
                self._append_log(f"  Skipping: {SCORES_FILENAME} already exists and overwrite is OFF.")
                skipped_existing_count += 1
                continue

            # Check stop event again before file creation
            if self.stop_event.is_set(): self._append_log(f"Stop requested detected before paths.jsonl creation for '{subdir_name}'. Halting."); break

            # --- Create paths.jsonl ---
            def progress_reporter(current, total, message):
                 if self.stop_event.is_set(): return # Avoid queueing updates if stopping
                 self.task_queue.put((self._update_preprocess_status, (current, total, f"{progress_prefix} {message}")))
            num_wavs, paths_msg = create_wav_jsonl(current_subdir_path, PATHS_FILENAME, progress_reporter)
            self._append_log(f"  1. Create {PATHS_FILENAME}: {paths_msg}")

            if num_wavs < 0:
                 error_count += 1; self._append_log(f"  ERROR: Failed to create {PATHS_FILENAME}. Skipping audio-aes.")
                 if self.stop_event.is_set(): self._append_log(f"Stop requested detected after paths.jsonl error for '{subdir_name}'. Halting."); break
                 continue
            elif num_wavs == 0:
                 skipped_no_wav_count += 1; self._append_log(f"  Skipping audio-aes: No WAV files found.")
                 if self.stop_event.is_set(): self._append_log(f"Stop requested detected after paths.jsonl check for '{subdir_name}'. Halting."); break
                 continue

            # Check stop event again before running the command
            if self.stop_event.is_set(): self._append_log(f"Stop requested just before running audio-aes for '{subdir_name}'. Halting."); break

            # --- Run audio-aes command ---
            self._append_log(f"  2. Running {audio_aes_cmd}...")
            self._update_status(f"{progress_prefix} Running audio-aes command...")
            self.update_idletasks() # Try to force GUI update

            run_start_time = time.time()
            # This call BLOCKS until audio-aes finishes or errors
            success, detailed_message = run_audio_aes(current_subdir_path, audio_aes_cmd, PATHS_FILENAME, SCORES_FILENAME, batch_size)
            run_time = time.time() - run_start_time

            # --- Log results (even if stop was requested during run) ---
            status_suffix = ""
            if self.stop_event.is_set():
                status_suffix = " (Stop was requested during run)" # Add note if stop was pending
                self._append_log(f"     Stop requested during audio-aes run for '{subdir_name}'. Processing loop will halt.")

            self._append_log(f"     Command finished in {run_time:.2f}s. Result: {'Success' if success else 'FAILURE'}{status_suffix}")
            if detailed_message: # Log the captured output from the command
                for line in detailed_message.strip().splitlines():
                    self._append_log(f"       {line}") # Indent command output
            elif not success and not self.stop_event.is_set(): # Log only if failed and no detailed msg and not stopping
                 self._append_log(f"       Command failed with no detailed output message.")

            if success: processed_count += 1
            else: error_count += 1 # Count errors even if stopping after this

            # If stop was requested during the run, break loop now after logging
            if self.stop_event.is_set(): break
            # --- End of Loop Iteration ---

        # --- Final Summary ---
        total_time = time.time() - start_time
        job_status = 'Completed normally' if not self.stop_event.is_set() else 'Halted by user request'
        summary_lines = [
            f"\n--- Preprocessing Job Summary ({job_status}) ---",
            f"Total Time: {total_time:.2f} seconds", f"Base Directory: {base_dir}",
            f"Subdirectories Scanned: {total_dirs}", f"Successfully Processed (audio-aes): {processed_count}",
            f"Errors Encountered: {error_count}", f"Skipped (No WAV files): {skipped_no_wav_count}",
            f"Skipped (scores.jsonl existed, overwrite OFF): {skipped_existing_count}",
            "--------------------------------------------------" ]
        summary_msg = "\n".join(summary_lines)
        flat_summary = summary_msg.replace('\n', ' | ')

        self._update_status(f"Preprocessing {job_status.lower()}. {flat_summary}")
        for line in summary_lines: self._append_log(line)

        # Notify user (show even if halted)
        self.task_queue.put((messagebox.showinfo, (f"Preprocessing {job_status}", f"{summary_msg}\n\nPlease reload the data if needed.", {'parent': self})))

        # <<< Clear the thread reference now that the job is done or stopped >>>
        self.preprocessing_thread = None


    def _on_closing(self):
        """ Handles window closing event. Sets stop event and destroys window. """
        print("Close button clicked. Requesting stop for background tasks...")
        self.stop_event.set() # <<< Signal the background thread to stop >>>

        # Give the background thread a moment to potentially react if not blocked
        # It won't help if blocked on subprocess.run, but doesn't hurt.
        # self.after(100, self._destroy_after_stop_check) # Alternative: delay destroy slightly

        if self.playback_enabled and pygame.mixer.get_init():
            try: pygame.mixer.music.stop(); pygame.mixer.quit(); print("Pygame mixer quit successfully.")
            except Exception as e: print(f"Error quitting pygame mixer: {e}")

        print("Destroying main window...")
        self.destroy()
        print("Application closed signal sent.")

    # Optional helper if delaying destroy:
    # def _destroy_after_stop_check(self):
    #     if self.preprocessing_thread and self.preprocessing_thread.is_alive():
    #         print("Background thread still active, waiting slightly more...")
    #         self.after(200, self._destroy_after_stop_check) # Check again
    #     else:
    #         print("Destroying main window now.")
    #         self.destroy()

# --- Main Execution ---
if __name__ == "__main__":
    print("Starting Audio Review Tool...")
    if sys.platform == "win32":
         try: from ctypes import windll; windll.shcore.SetProcessDpiAwareness(1)
         except Exception as e: print(f"Could not set DPI awareness: {e}")

    print("DEBUG: Creating AudioReviewApp instance...")
    app = AudioReviewApp()
    print("DEBUG: AudioReviewApp instance created.")

    if not FFMPEG_AVAILABLE:
         print("\nWARNING: FFmpeg executable was not found in the system's PATH.")
         print("         MP3 export functionality will be disabled.")

    # <<< Add try/except/finally block for graceful shutdown >>>
    try:
        print("DEBUG: Starting app.mainloop()...")
        app.mainloop()
    except KeyboardInterrupt:
        print("\nCtrl+C detected. Requesting stop...")
        if hasattr(app, 'stop_event'):
             app.stop_event.set() # Signal the background thread
        print("Destroying main window (from Ctrl+C)...")
        # Need to destroy the app window to exit mainloop cleanly after Ctrl+C
        if app.winfo_exists():
             app.destroy()
    finally:
        print("DEBUG: Main loop finished or interrupted.")
        # Final check to ensure stop event is set if app object still exists
        if 'app' in locals() and hasattr(app, 'stop_event') and not app.stop_event.is_set():
             print("DEBUG: Setting stop event in finally block.")
             app.stop_event.set()
        # Give daemon threads a very brief moment if needed
        # time.sleep(0.2)
        print("Exiting script.")
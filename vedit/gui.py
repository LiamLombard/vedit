from multiprocessing import Queue, Process
from queue import Empty
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from vedit.video_editor import process_dir


import os
import signal
import psutil


def kill_children(sig=signal.SIGTERM, timeout=None, on_terminate=None):
    """Kill a process tree (including grandchildren) with signal
    "sig" and return a (gone, still_alive) tuple.
    "on_terminate", if specified, is a callback function which is
    called as soon as a child terminates.
    """
    main_pid = os.getpid()
    parent = psutil.Process(main_pid)
    children = parent.children(recursive=True)
    for p in children:
        try:
            p.send_signal(sig)
        except psutil.NoSuchProcess:
            pass
    gone, alive = psutil.wait_procs(children, timeout=timeout, callback=on_terminate)
    return (gone, alive)


class VEditGUI:
    def __init__(self):
        self.root = root = tk.Tk()
        self.message_queue = Queue()
        self.selected_file_path: Path | None = None

        self.root = root
        self.root.title("Video Processor")

        self.file_path_label = tk.Label(root, text="Selected Folder:")
        self.file_path_label.pack(pady=10)

        self.select_button = tk.Button(
            root, text="Select Folder", command=self.select_file
        )
        self.select_button.pack(pady=10)

        self.process_button = tk.Button(
            root, text="Process Folder", command=self.process_folder
        )
        self.process_button.pack(pady=10)
        self.process_button.config(state=tk.DISABLED)

        self.stop_button = tk.Button(
            root, text="Stop Processing", command=self.stop_process
        )
        self.stop_button.pack(pady=10)
        self.stop_button.config(state=tk.DISABLED)

        self.progress_bar = ttk.Progressbar(
            root, orient="horizontal", length=650, mode="determinate"
        )
        self.progress_bar.pack(pady=10)

        self.status_label = tk.Label(root, text="")
        self.status_label.pack(pady=10)

        self.video_editing_process: Process | None = None

    def step(self, step: float) -> None:
        self.progress_bar.step(step)
        self.root.update()

    def select_file(self):
        file_path = filedialog.askdirectory()
        self.file_path_label.config(text=f"Selected Folder: {file_path}")
        self.selected_file_path = Path(file_path)
        self.process_button.config(state=tk.NORMAL)

    def stop_process(self):
        kill_children()
        self.video_editing_process = None
        self.selected_file_path = None
        self.file_path_label.config(
            text="Processing stopped. Please select a new file."
        )
        self.status_label.config(text="")
        self.root.update()
        self.process_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.progress_bar.stop()

    def process_folder(self) -> None:
        if not self.selected_file_path:
            self.file_path_label.config(text="Please select a folder first.")
            return
        if self.video_editing_process is not None:
            return

        # Make sure the queue is clear by overwriting it.
        self.message_queue = Queue()

        self.video_editing_process = Process(
            target=process_dir,
            args=(self.selected_file_path, self.message_queue),
            daemon=True,
        )
        self.video_editing_process.start()

        self.status_label.config(text="Starting processing!")

        self.process_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.root.after(1000, self.check_progress)

    def check_progress(self) -> None:
        if (
            self.video_editing_process is None
            or self.message_queue.empty()
            and not self.video_editing_process.is_alive()
        ):
            # something has gone wrong...
            self.status_label.config(
                text="FFmpeg seems to have failed, please check the logfile for clues."
            )
            self.stop_button.config(state=tk.DISABLED)
            self.root.update()
            return

        if self.message_queue.empty() and self.video_editing_process.is_alive():
            self.root.after(1000, self.check_progress)
            return

        try:
            message = self.message_queue.get(block=False, timeout=2)
        except Empty:
            message = None

        match message:
            case ("step", step, message):
                self.step(step)
                self.status_label.config(text=message)
            case ("done", output_path):
                self.video_editing_process.join()
                self.video_editing_process = None
                self.selected_file_path = None
                self.file_path_label.config(
                    text=f"File processed and saved as: {output_path}"
                )
                self.status_label.config(text="Done!")
                self.stop_button.config(state=tk.DISABLED)
                self.root.update()
                return
            case ("skipped", output_path):
                self.video_editing_process.join()
                self.video_editing_process = None
                self.selected_file_path = None
                self.file_path_label.config(
                    text=f"{output_path} Already exists, nothing to do. If the file is bad, please delete it and try again."
                )
                self.status_label.config(text="Nothing to do!")
                self.stop_button.config(state=tk.DISABLED)
                self.root.update()
                return
            case None:
                pass
            case _:
                raise RuntimeError("Unknown response from processing process")

        self.root.update()
        self.root.after(1000, self.check_progress)

    def run(self):
        try:
            self.root.mainloop()
        except (RuntimeError, KeyboardInterrupt):
            if self.video_editing_process is not None:
                self.video_editing_process.stop()
                self.video_editing_process.join()

            self.system.reset()

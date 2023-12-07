from queue import Queue, Empty
from threading import Thread
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from vedit.video_editor import process_dir


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

        self.progress_bar = ttk.Progressbar(
            root, orient="horizontal", length=650, mode="determinate"
        )
        self.progress_bar.pack(pady=10)

        self.status_label = tk.Label(root, text="")
        self.status_label.pack(pady=10)

        self.processing_thread: Thread | None = None

    def step(self, step: float) -> None:
        self.progress_bar.step(step)
        self.root.update()

    def select_file(self):
        file_path = filedialog.askdirectory()
        self.file_path_label.config(text=f"Selected Folder: {file_path}")
        self.selected_file_path = Path(file_path)
        self.process_button.config(state=tk.NORMAL)

    def process_folder(self) -> None:
        if not self.selected_file_path:
            self.file_path_label.config(text="Please select a folder first.")
            return
        if self.processing_thread is not None:
            return

        # Make sure the queue is clear by overwriting it.
        self.message_queue = Queue()

        self.processing_thread = Thread(
            target=process_dir,
            args=(self.selected_file_path, self.message_queue),
            daemon=True,
        )
        self.processing_thread.start()

        self.process_button.config(state=tk.DISABLED)
        self.root.after(1000, self.check_progress)

    def check_progress(self) -> None:
        if self.message_queue.empty() and self.processing_thread.is_alive():
            self.root.after(1000, self.check_progress)
            return
        elif self.message_queue.empty() and not self.processing_thread.is_alive():
            raise RuntimeError("fmmpeg seems to have failed...")

        try:
            message = self.message_queue.get(block=False, timeout=2)
        except Empty:
            message = None

        match message:
            case ("step", step, message):
                self.step(step)
                self.status_label.config(text=message)
            case ("done", output_path):
                self.processing_thread.join()
                self.processing_thread = None
                self.selected_file_path = None
                self.file_path_label.config(
                    text=f"File processed and saved as: {output_path}"
                )
                self.status_label.config(text="Done!")
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
            if self.processing_thread is not None:
                self.processing_thread.stop()
                self.processing_thread.join()

            self.system.reset()

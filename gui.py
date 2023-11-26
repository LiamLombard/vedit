from dataclasses import dataclass
import os
from queue import Queue, Empty
import subprocess
import sys
from threading import Thread
import tkinter as tk
import tomllib
from datetime import datetime
from io import TextIOWrapper
from pathlib import Path
from tempfile import TemporaryDirectory
from tkinter import filedialog, ttk
from typing import TextIO


@dataclass(frozen=True)
class Config:
    vid_split_secs: int = 60
    speed_multiplier: int = 6


class System:
    def __init__(self, config_file: Path | None = None) -> None:
        self.original_stdout: TextIO = sys.stdout
        self.original_stderr: TextIO = sys.stderr
        self.out_stream: TextIOWrapper = sys.stdout
        self.config_file: Path = config_file or Path("config.toml")

        if self.config_file.exists():
            self.config = Config(**tomllib.loads(self.config_file.read_text()))
        else:
            self.config = Config()

        self.log_dir: Path = Path.cwd() / "logs"

    def new_logfile(self) -> None:
        if not self.log_dir.exists():
            self.log_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now().strftime("%Y-%m-%dT%H%M%S")
        self.out_stream = self.log_dir.joinpath(f"{now}.log").open("a+")
        sys.stdout = self.out_stream
        sys.stderr = self.out_stream

    def reset(self) -> None:
        self.out_stream.close()
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr

    def writeline(self, s: str) -> None:
        self.out_stream.write(s)
        self.out_stream.write("\n")
        self.out_stream.flush()

    def ffmpeg(self, *args: str) -> None:
        cmd = ["ffmpeg", *args]
        self.writeline(f"Running command: {' '.join(cmd)}")

        res = subprocess.run(
            args=cmd,
            stdout=self.out_stream,
            stderr=self.out_stream,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        res.check_returncode()
        self.writeline("ffmpeg finished successfully!")

    def process_file(self, selected_file: Path, message_queue: Queue) -> None:
        self.new_logfile()

        output_path = (
            selected_file.parent
            / f"{selected_file.stem}_processed{selected_file.suffix}"
        )

        with TemporaryDirectory() as tmp_path:
            tmp_path = Path(tmp_path)
            tmp_path.mkdir(parents=True, exist_ok=True)
            files = self.ffmpeg_split(selected_file, tmp_path=tmp_path)

            step = 100 / (len(files) + 2)
            message_queue.put(("step", step))

            processed_paths = []
            for file in files:
                processed_paths.append(self.ffmpeg_edit(file))
                message_queue.put(("step", step))

            self.ffmpeg_combine_and_speedup(
                processed_paths, output_path=output_path, tmp_path=tmp_path
            )
            message_queue.put(("step", step))

        message_queue.put("done")

    def ffmpeg_split(self, in_file: Path, tmp_path: Path) -> Path:
        seconds = self.config.vid_split_secs
        self.ffmpeg(
            "-y",
            "-i",
            in_file.as_posix(),
            "-c",
            "copy",
            "-map",
            "0:v",
            "-segment_time",
            str(seconds),
            "-f",
            "segment",
            "-reset_timestamps",
            "1",
            tmp_path.joinpath(f"%03d{in_file.suffix}").as_posix(),
        )
        return list(tmp_path.glob(f"*{in_file.suffix}"))

    def ffmpeg_combine_and_speedup(
        self,
        processed_paths: list[Path],
        output_path: Path,
        tmp_path: Path,
    ) -> Path:
        concat_file = tmp_path / "concat.txt"
        concat_file.write_text(
            "\r\n".join([f"file {f.as_posix()}" for f in processed_paths])
        )

        self.ffmpeg(
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_file.as_posix(),
            "-vf",
            f"setpts={1/self.config.speed_multiplier}*PTS",
            "-an",
            output_path.as_posix(),
        )
        return output_path

    def ffmpeg_edit(self, in_file: Path) -> Path:
        output_path = in_file.parent / f"{in_file.stem}_processed{in_file.suffix}"

        self.ffmpeg(
            "-y",
            "-i",
            in_file.as_posix(),
            "-vf",
            ";".join(
                [
                    "split=2[full][masked]",
                    "[masked]drawbox=w=iw*0.2:h=ih:x=0:y=0:t=fill:c=white,drawbox=w=iw:h=ih*0.2:x=0:y=ih*0.8:t=fill:c=white,mpdecimate[deduped]",
                    "[deduped][full]overlay=shortest=1,setpts=N/FRAME_RATE/TB",
                ],
            ),
            "-an",
            output_path.as_posix(),
        )

        return output_path


class FileProcessorApp:
    def __init__(self, root: tk.Tk, system: System):
        self.system = system
        self.message_queue = Queue()
        self.selected_file_path: Path | None = None

        self.root = root
        self.root.title("Video Processor")

        self.file_path_label = tk.Label(root, text="Selected File:")
        self.file_path_label.pack(pady=10)

        self.select_button = tk.Button(
            root, text="Select File", command=self.select_file
        )
        self.select_button.pack(pady=10)

        self.process_button = tk.Button(
            root, text="Process File", command=self.process_file
        )
        self.process_button.pack(pady=10)
        self.process_button.config(state=tk.DISABLED)

        self.progress_bar = ttk.Progressbar(
            root, orient="horizontal", length=400, mode="determinate"
        )
        self.progress_bar.pack(pady=10)

        self.processing_thread: Thread | None = None

    def step(self, step: float) -> None:
        self.progress_bar.step(step)
        self.root.update()

    def select_file(self):
        file_path = filedialog.askopenfilename()
        self.file_path_label.config(text=f"Selected File: {file_path}")
        self.selected_file_path = Path(file_path)
        self.process_button.config(state=tk.NORMAL)

    def process_file(self) -> None:
        if not self.selected_file_path:
            self.file_path_label.config(text="Please select a file first.")
            return
        if self.processing_thread is not None:
            return

        self.message_queue = Queue()  # make sure this queue is clear
        self.processing_thread = Thread(
            target=self.system.process_file,
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
            case ("step", step):
                self.step(step)
            case ("done", output_path):
                self.processing_thread.join()
                self.processing_thread = None
                self.selected_file_path = None
                self.file_path_label.config(
                    text=f"File processed and saved as: {output_path}"
                )
                self.root.update()
                return
            case None:
                pass
            case _:
                raise RuntimeError("Unknown response from processing process")

        self.root.after(1000, self.check_progress)

    def run(self):
        try:
            self.root.mainloop()
        except (RuntimeError, KeyboardInterrupt):
            if self.processing_thread is not None:
                self.processing_thread.stop()
                self.processing_thread.join()

            self.system.reset()


if __name__ == "__main__":
    if os.name == "nt":
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)

    system = System()
    root = tk.Tk()

    app = FileProcessorApp(root, system)
    app.run()

from dataclasses import dataclass, asdict
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
import traceback
from typing import Iterator, Self, TextIO


@dataclass(frozen=True)
class Config:
    video_split_secs: int = 60
    speed_multiplier: int = 6

    @staticmethod
    def load(config_file: Path | None = None) -> Self:
        config_file: Path = config_file or Path("config.toml")

        if config_file.exists():
            config = Config(**tomllib.loads(config_file.read_text()))
        else:
            config = Config()
            default_toml = "\n".join(
                f"{key} = {value}" for key, value in asdict(config).items()
            )
            config_file.write_text(default_toml)

        return config


def parse_filename(p: Path) -> datetime:
    parsing_options = [
        lambda: datetime.strptime(p.stem, "%Y-%m-%d %H-%M-%S"),
        lambda: datetime.fromisoformat(p.stem),
        lambda: p.stat().st_mtime,
    ]
    for parse_attempt in parsing_options:
        try:
            return parse_attempt()
        except Exception:
            pass

    raise RuntimeError("Could not get a meaningful value to order video files by")


class Logger:
    def __init__(self) -> None:
        self.original_stdout: TextIO = sys.stdout
        self.original_stderr: TextIO = sys.stderr
        self.out_stream: TextIOWrapper = sys.stdout

        self.log_dir: Path = Path.cwd() / "logs"

    def make_new_logfile(self) -> None:
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

    def exception(self, s: str) -> None:
        self.writeline(s)
        traceback.print_exc()


class FFmpeg:
    def ffmpeg(self, *args: str) -> None:
        cmd = ["ffmpeg", *args]
        logger.writeline(f"Running command: {' '.join(cmd)}")

        res = subprocess.run(
            args=cmd,
            stdout=logger.out_stream,
            stderr=logger.out_stream,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        res.check_returncode()
        logger.writeline("ffmpeg finished successfully!")

    def split(
        self, in_file: Path, tmp_path: Path, seconds: int, prefix: str = ""
    ) -> list[Path]:
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
            tmp_path.joinpath(f"{prefix}%04d{in_file.suffix}").as_posix(),
        )
        return sorted(tmp_path.glob(f"{prefix}*{in_file.suffix}"), key=lambda f: f.name)

    def combine_and_speedup(
        self,
        processed_paths: list[Path],
        speed_multiplier: int,
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
            f"setpts={1/speed_multiplier}*PTS",
            "-an",
            output_path.as_posix(),
        )
        return output_path

    def dedupe(self, in_file: Path) -> Path:
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

    def edit(
        self, in_file: Path, seconds: int, min_split_time: int = 1, n_splits: int = 2
    ) -> Iterator[Path]:
        """Handles the main deduplication logic for a file.

        This is an error prone action, where we often run out of memory while trying to process 4K video.
        To try and mitigate we split file into `n_splits` for every failure and try again.
        Down to a minimum of 1 second per split file.
        """
        try:
            yield self.dedupe(in_file=in_file)
            return
        except subprocess.CalledProcessError:
            logger.exception("Failed to process file - probably ran out of memory.")

        new_time = seconds // n_splits
        logger.writeline(f"Splitting file length down to {new_time} and retrying...")

        if new_time < min_split_time:
            raise RuntimeError(
                "Something has gone wrong, we couldn't process very short videos."
            )

        files = self.split(
            in_file, in_file.parent, seconds=new_time, prefix=f"{in_file.name}_"
        )
        for file in files:
            yield from self.edit(in_file=file, seconds=new_time)


def process_dir(selected_dir: Path, message_queue: Queue) -> None:
    config = Config.load()
    ffmpeg = FFmpeg()

    logger.make_new_logfile()

    output_path = selected_dir / "processed.mkv"

    files_to_process = sorted(selected_dir.glob("*.mkv"), key=parse_filename)

    n_digits = len(str(len(files_to_process))) + 1

    with TemporaryDirectory() as tmp_path:
        tmp_path = Path(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)

        message_queue.put(("step", 0, "Splitting video files into chunks"))
        files: list[Path] = []
        for i, video_file in enumerate(files_to_process):
            split_files = ffmpeg.split(
                video_file,
                tmp_path=tmp_path,
                seconds=config.video_split_secs,
                prefix=f"{i:0{n_digits}}_",
            )
            files.extend(split_files)

        step = 100 / (len(files) + 2)
        message_queue.put(("step", step, "Starting to process files"))

        processed_paths = []
        for i, file in enumerate(files):
            msg = f"Processing: {file.as_posix()} ({i+1}/{len(files)})"
            message_queue.put(("step", step, msg))
            processed_paths.extend(ffmpeg.edit(file, seconds=config.video_split_secs))

        message_queue.put(("step", 0, "Merging/Speeding up files"))
        ffmpeg.combine_and_speedup(
            processed_paths,
            speed_multiplier=config.speed_multiplier,
            output_path=output_path,
            tmp_path=tmp_path,
        )
        message_queue.put(("step", step, "Merging Complete"))

    message_queue.put(("done", output_path))


class FileProcessorApp:
    def __init__(self, root: tk.Tk):
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


if __name__ == "__main__":
    if os.name == "nt":
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)

    logger = Logger()

    root = tk.Tk()
    app = FileProcessorApp(root)
    app.run()

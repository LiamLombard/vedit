import os
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from io import TextIOWrapper
from pathlib import Path
from tempfile import TemporaryDirectory
from tkinter import filedialog, ttk
from typing import TextIO


class System:
    def __init__(self) -> None:
        self.original_stdout: TextIO = sys.stdout
        self.original_stderr: TextIO = sys.stderr
        self.out_stream: TextIOWrapper = None

    def new_logfile(self) -> None:
        now = datetime.now().strftime("%Y-%m-%dT%H%M%S")
        self.out_stream = Path.cwd().joinpath(f"{now}.log").open("a+")
        sys.stdout = self.out_stream
        sys.stderr = self.out_stream

    def reset(self) -> None:
        self.out_stream.close()
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr

    def ffmpeg(self, *args, retries: int = 3) -> None:
        for _ in range(retries):
            res = subprocess.run(
                args=["ffmpeg", *args],
                stdout=self.out_stream,
                stderr=self.out_stream,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if res.returncode == 0:
                print("ffmpeg finished successfully!")
                return
            print("ffmpeg failed! Retrying...")
        res.check_returncode()


class FileProcessorApp:
    def __init__(self, root: tk.Tk, system: System):
        self.system = system
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

    def step(self, step: float) -> None:
        self.progress_bar.step(step)
        self.root.update()

    def select_file(self):
        file_path = filedialog.askopenfilename()
        self.file_path_label.config(text=f"Selected File: {file_path}")
        self.selected_file_path = Path(file_path)
        self.process_button.config(state=tk.NORMAL)

    def process_file(self, video_split_s: int = 100):
        self.system.new_logfile()
        if not self.selected_file_path:
            self.file_path_label.config(text="Please select a file first.")
            return

        output_path = (
            self.selected_file_path.parent
            / f"{self.selected_file_path.stem}_processed{self.selected_file_path.suffix}"
        )

        with TemporaryDirectory() as tmp_path:
            tmp_path = Path(tmp_path)
            tmp_path.mkdir(parents=True, exist_ok=True)
            files = self.ffmpeg_split(
                self.selected_file_path, seconds=video_split_s, tmp_path=tmp_path
            )

            step = 100 / (len(files) + 2)
            self.step(step)

            processed_paths = []
            for file in files:
                processed_paths.append(self.ffmpeg_edit(file))
                self.step(step)

            self.ffmpeg_combine_and_speedup(
                processed_paths, output_path=output_path, tmp_path=tmp_path
            )
            self.step(step)

        self.file_path_label.config(text=f"File processed and saved as: {output_path}")
        self.progress_bar.stop()

    def ffmpeg_split(self, in_file: Path, seconds: int, tmp_path: Path) -> Path:
        self.system.ffmpeg(
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
            tmp_path.joinpath(f"%03d{in_file.suffix}"),
        )
        return list(tmp_path.glob(f"*{in_file.suffix}"))

    def ffmpeg_combine_and_speedup(
        self,
        processed_paths: list[Path],
        output_path: Path,
        tmp_path: Path,
        speed_multi: int = 6,
    ) -> Path:
        concat_file = tmp_path / "concat.txt"
        concat_file.write_text(
            "\r\n".join([f"file {f.as_posix()}" for f in processed_paths])
        )

        self.system.ffmpeg(
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_file.as_posix(),
            "-vf",
            f"setpts={1/speed_multi}*PTS",
            "-an",
            output_path.as_posix(),
        )
        return output_path

    def ffmpeg_edit(self, in_file: Path) -> Path:
        output_path = in_file.parent / f"{in_file.stem}_processed{in_file.suffix}"

        self.system.ffmpeg(
            "-y",
            "-i",
            in_file.as_posix(),
            "-vf",
            ",".join(
                [
                    "split=2[full][masked];[masked]drawbox=w=iw*0.2:h=ih:x=0:y=0:t=fill:c=white",
                    "drawbox=w=iw:h=ih*0.2:x=0:y=ih*0.8:t=fill:c=white",
                    "mpdecimate[deduped];[deduped][full]overlay=shortest=1",
                    "setpts=N/FRAME_RATE/TB",
                ],
            ),
            "-b:v",
            "1000k",
            "-an",
            output_path.as_posix(),
        )

        return output_path

    def run(self):
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.system.reset()


if __name__ == "__main__":
    if os.name == "nt":
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)

    system = System()
    root = tk.Tk()

    app = FileProcessorApp(root, system)
    app.run()

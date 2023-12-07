from functools import lru_cache
import sys
from datetime import datetime
from io import TextIOWrapper
from pathlib import Path
import traceback
from typing import TextIO


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


@lru_cache
def get_logger() -> Logger:
    return Logger()

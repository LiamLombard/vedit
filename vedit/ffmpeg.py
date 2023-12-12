from decimal import Decimal
import subprocess
from pathlib import Path
from typing import Iterator

from vedit.logger import get_logger
from vedit.db import DB

logger = get_logger()


class FFmpeg:
    def run(self, *args: str, program: str = "ffmpeg") -> None:
        cmd = [program, *args]
        logger.writeline(f"Running command: {' '.join(cmd)}")

        res = subprocess.run(
            args=cmd,
            stdout=logger.out_stream,
            stderr=logger.out_stream,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        res.check_returncode()
        logger.writeline("ffmpeg finished successfully!")

    def get_video_duration(self, video_file: Path) -> Decimal:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            video_file.as_posix(),
        ]
        logger.writeline(f"Running command: {' '.join(cmd)}")

        res = subprocess.run(
            args=cmd, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW
        )
        res.check_returncode()
        logger.writeline("ffprobe finished successfully!")
        return Decimal(res.stdout.decode())

    def split(
        self, in_file: Path, tmp_path: Path, seconds: int, prefix: str = ""
    ) -> list[Path]:
        self.run(
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

    def cut_section(
        self, in_file: Path, tmp_path: Path, start_time: Decimal, end_time: Decimal
    ) -> list[Path]:
        out_file = tmp_path.joinpath(
            f"{in_file.stem}-{start_time}s-{end_time}s{in_file.suffix}"
        )
        self.run(
            "-y",
            "-ss",
            str(start_time),
            "-i",
            in_file.as_posix(),
            "-c",
            "copy",
            "-t",
            str(end_time - start_time),
            "-map",
            "0:v",
            "-avoid_negative_ts",
            "make_zero",
            out_file.as_posix(),
        )
        return out_file

    def combine_and_speedup(
        self,
        processed_paths: list[Path],
        speed_multiplier: int,
        output_path: Path,
        tmp_path: Path,
    ) -> Path:
        concat_file = tmp_path / "concat.txt"
        concat_file.write_text(
            "\r\n".join([f"file '{f.as_posix()}'" for f in processed_paths])
        )

        self.run(
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

    def dedupe(self, in_file: Path, output_path: Path) -> Path:
        self.run(
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

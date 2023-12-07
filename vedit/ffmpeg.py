import subprocess
from pathlib import Path
from typing import Iterator

from vedit.logger import get_logger

logger = get_logger()


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

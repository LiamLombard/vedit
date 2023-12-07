from datetime import datetime
from queue import Queue
from pathlib import Path
from tempfile import TemporaryDirectory

from vedit.logger import get_logger
from vedit.config import Config
from vedit.ffmpeg import FFmpeg

logger = get_logger()


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

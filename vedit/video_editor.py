from datetime import datetime
from decimal import Decimal
from itertools import chain
from queue import Queue
from pathlib import Path
from shutil import rmtree
import subprocess
from typing import Iterator
from vedit.db import DB, EditingTracker

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


def process_dir(
    selected_dir: Path,
    message_queue: Queue,
    ffmpeg: FFmpeg | None = None,
    config: Config | None = None,
    db: DB | None = None,
) -> None:
    config = config or Config.load()
    logger.make_new_logfile()
    tmp_path = selected_dir / ".vedit"
    tmp_path.mkdir(parents=True, exist_ok=True)

    db = db or DB.create_db(tmp_path / "db.sqlite")

    ffmpeg = ffmpeg or FFmpeg()

    out_path = selected_dir / "processed.mkv"

    if out_path.exists():
        message_queue.put(("skipped", out_path))

    files_to_process = sorted(selected_dir.glob("*.mkv"), key=parse_filename)
    total_duration = sum(map(ffmpeg.get_video_duration, files_to_process))
    total_processed_duration = db.get_total_processed_duration(files_to_process)

    start = 95 * ((total_processed_duration) / (total_duration))
    msg = (
        "Restarting from where we left off"
        if start != 0
        else "Commencing video editing"
    )
    message_queue.put(("step", start, msg))

    for video_file in files_to_process:
        file_duration: Decimal = ffmpeg.get_video_duration(video_file=video_file)

        vs = EditingTracker(
            video_file, file_duration, split_time=config.video_split_secs, db=db
        )

        while (current_range := vs.next()) is not None:
            start_time, end_time = current_range
            range_str = f"{start_time}s-{end_time}s"
            message_queue.put(("step", 0, f"Cutting out {range_str} from {video_file}"))
            sub_file = ffmpeg.cut_section(
                video_file, tmp_path=tmp_path, start_time=start_time, end_time=end_time
            )

            message_queue.put(("step", 0, f"Processing {range_str} of {video_file}"))
            out_path = sub_file.parent / f"{sub_file.stem}_processed{sub_file.suffix}"
            try:
                ffmpeg.dedupe(sub_file, out_path)
            except subprocess.CalledProcessError:
                sub_file.unlink(missing_ok=True)
                out_path.unlink(missing_ok=True)
                vs.failed(current_range)
                continue

            step = 95 * ((end_time - start_time) / (total_duration))
            message_queue.put(
                ("step", step, f"Processing {start_time}s-{end_time}s of {video_file}")
            )
            vs.success(out_path, current_range)
            sub_file.unlink(missing_ok=True)

    processed_paths = list(
        chain.from_iterable(map(db.get_merge_order, files_to_process))
    )

    message_queue.put(("step", 0, "Merging/Speeding up files"))
    ffmpeg.combine_and_speedup(
        processed_paths,
        speed_multiplier=config.speed_multiplier,
        output_path=out_path,
        tmp_path=tmp_path,
    )
    message_queue.put(("step", 5, "Merging Complete"))

    message_queue.put(("done", out_path))

    db.close()
    rmtree(tmp_path)

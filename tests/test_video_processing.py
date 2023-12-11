from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator
from unittest.mock import MagicMock, patch
from queue import Queue
import pytest
from vedit.config import Config
from vedit.db import DB

from vedit.video_editor import process_dir


@pytest.fixture()
def tmp_dir() -> Iterator[DB]:
    with TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


def test_end_to_end_happy_case_mocked(tmp_dir: Path):
    msg_queue = Queue()
    fake_files = [
        tmp_dir / ("2023-01-01 00-00-00.mkv"),
        tmp_dir / ("2023-01-02 00-00-00.mkv"),
    ]
    for fake_file in fake_files:
        fake_file.touch()

    ffmpeg = MagicMock()

    ffmpeg.split.return_value = [tmp_dir / f"{i}.mkv" for i in range(10)]

    def edit_mock(file: Path, seconds: float) -> Iterator[Path]:
        yield file.parent / f"{file.stem}_processed{file.suffix}"

    ffmpeg.edit.side_effect = edit_mock
    ffmpeg.combine_and_speedup.side_effect = lambda x, *args, **kw: x

    db = DB.create_db(tmp_dir / "db.sqlite")
    db.close = MagicMock()

    process_dir(tmp_dir, msg_queue, ffmpeg, Config(), db=db)

    assert not tmp_dir.joinpath(".vedit").exists()

    assert db.read_events("split_file") == [f.as_posix() for f in fake_files]
    assert db.read_events("edited_file") == [
        (tmp_dir / f"{i}.mkv").as_posix() for i in range(10)
    ]
    assert db.read_events("file_for_merging") == [
        (tmp_dir / f"{i}_processed.mkv").as_posix() for i in range(10)
    ]

    db.conn.close()


def test_end_to_end_stop_and_restart_mocked(tmp_dir: Path):
    msg_queue = Queue()
    fake_files = [
        tmp_dir / ("2023-01-01 00-00-00.mkv"),
        tmp_dir / ("2023-01-02 00-00-00.mkv"),
    ]
    for fake_file in fake_files:
        fake_file.touch()

    ffmpeg = MagicMock()

    ffmpeg.split.return_value = [tmp_dir / f"{i}.mkv" for i in range(10)]

    # Editing one of the files will fail to process
    def edit_mock(file: Path, seconds: float) -> Iterator[Path]:
        if "5" in file.name:
            raise KeyboardInterrupt
        yield file.parent / f"{file.stem}_processed{file.suffix}"

    ffmpeg.edit.side_effect = edit_mock
    ffmpeg.combine_and_speedup.side_effect = lambda x, *args, **kw: x

    db = DB.create_db(tmp_dir / "db.sqlite")
    db.close = MagicMock()

    try:
        process_dir(tmp_dir, msg_queue, ffmpeg, Config(), db=db)
    except KeyboardInterrupt:
        pass

    assert tmp_dir.joinpath(".vedit").exists()

    assert db.read_events("split_file") == [f.as_posix() for f in fake_files]
    assert db.read_events("edited_file") == [
        (tmp_dir / f"{i}.mkv").as_posix() for i in range(5)
    ]
    assert db.read_events("file_for_merging") == [
        (tmp_dir / f"{i}_processed.mkv").as_posix() for i in range(5)
    ]

    # pretend whatever issue caused the failure the first time was fixed
    def edit_mock(file: Path, seconds: float) -> Iterator[Path]:
        yield file.parent / f"{file.stem}_processed{file.suffix}"

    ffmpeg.edit.side_effect = edit_mock

    process_dir(tmp_dir, msg_queue, ffmpeg, Config(), db=db)

    assert not tmp_dir.joinpath(".vedit").exists()
    assert db.read_events("split_file") == [f.as_posix() for f in fake_files]
    assert db.read_events("edited_file") == [
        (tmp_dir / f"{i}.mkv").as_posix() for i in range(10)
    ]
    assert db.read_events("file_for_merging") == [
        (tmp_dir / f"{i}_processed.mkv").as_posix() for i in range(10)
    ]

    db.conn.close()

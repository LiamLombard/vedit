from decimal import Decimal
from pathlib import Path


from vedit.ffmpeg import FFmpeg


def test_duration():
    ffmpeg = FFmpeg()
    test_file = Path(__file__).parent.parent / "vids" / "2023-08-31 09-13-04.mkv"

    assert ffmpeg.get_video_duration(test_file) == Decimal("3573.269000")

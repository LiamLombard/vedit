from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator

import pytest

from vedit.db import DB, EditingTracker

dummpy_path = Path("dummy")


@pytest.fixture()
def tracker() -> Iterator[DB]:
    with TemporaryDirectory() as tmp_dir:
        db = DB.create_db(Path(tmp_dir) / "db.sqlite")
        tracker = EditingTracker(
            Path("."), Decimal(10), Decimal(5), split_factor=Decimal(2), db=db
        )
        yield tracker
        db.close()


def test_simple_logic(tracker: EditingTracker):
    range1 = tracker.next()
    assert range1 == (Decimal(0), Decimal(5))
    tracker.success(dummpy_path, range1)
    range2 = tracker.next()
    assert range2 == (Decimal(5), Decimal(10))
    tracker.success(dummpy_path, range2)

    assert tracker.done()
    assert tracker.next() is None


def test_with_some_failures(tracker: EditingTracker):
    first_range = (Decimal(0), Decimal(5))
    assert tracker.next() == first_range
    tracker.failed(first_range)

    second_range = tracker.next()
    assert second_range == (Decimal(0), Decimal("2.5"))
    second_range = tracker.next()
    tracker.success(dummpy_path, second_range)

    third_range = tracker.next()
    assert third_range == (Decimal("2.5"), Decimal("7.5"))
    tracker.success(dummpy_path, third_range)

    fouth_range = tracker.next()
    assert fouth_range == (Decimal("7.5"), Decimal("10"))
    tracker.success(dummpy_path, fouth_range)

    assert tracker.done()
    assert tracker.next() is None


def test_handles_resumption(tracker: EditingTracker):
    tracker.db.log_status(
        tracker.path, dummpy_path, (Decimal(0), Decimal(5)), "success"
    )
    tracker.db.log_status(tracker.path, None, (Decimal(0), Decimal(7.5)), "failed")

    first_range = (Decimal(5), Decimal(10))
    assert tracker.next() == first_range
    tracker.success(dummpy_path, first_range)

    assert tracker.done()
    assert tracker.next() is None


def test_handles_resumption_when_ended_at_failure(tracker: EditingTracker):
    tracker.db.log_status(tracker.path, None, (Decimal(0), Decimal(5)), "failed")

    first_range = (Decimal(0), Decimal(2.5))
    assert tracker.next() == first_range
    tracker.success(dummpy_path, first_range)

    second_range = (Decimal(2.5), Decimal(7.5))
    assert tracker.next() == second_range
    tracker.success(dummpy_path, second_range)

    third_range = (Decimal(7.5), Decimal(10))
    assert tracker.next() == third_range
    tracker.success(dummpy_path, third_range)

    assert tracker.done()
    assert tracker.next() is None


def test_handles_gaps(tracker: EditingTracker):
    tracker.db.log_status(
        tracker.path, dummpy_path, (Decimal(2.5), Decimal(5)), "success"
    )

    first_range = (Decimal(0), Decimal(2.5))
    assert tracker.next() == first_range
    tracker.success(dummpy_path, first_range)

    second_range = (Decimal(5), Decimal(10))
    assert tracker.next() == second_range
    tracker.success(dummpy_path, second_range)

    assert tracker.done()
    assert tracker.next() is None

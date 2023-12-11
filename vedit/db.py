from decimal import Decimal
import sqlite3
from pathlib import Path

TimeRange = tuple[Decimal, Decimal]


def merge_intervals(intervals: set[TimeRange]) -> list[TimeRange]:
    # Sort intervals based on the start time
    sorted_intervals = sorted(intervals, key=lambda x: x[0])

    merged = []
    for interval in sorted_intervals:
        start, end = interval
        # If the merged list is empty or if the current interval does not overlap with the last one
        if not merged or start > merged[-1][1]:
            merged.append(interval)
        else:
            # Merge overlapping intervals
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))

    return merged


def find_uncovered_gaps(
    intervals: set[TimeRange], max_range: TimeRange
) -> list[TimeRange]:
    if not intervals:
        return [max_range]

    merged_intervals = merge_intervals(intervals)
    uncovered_gaps = []

    # Check the gap between the first interval and the lower bound of the max range
    if merged_intervals and merged_intervals[0][0] > min(max_range):
        uncovered_gaps.append((Decimal(0), merged_intervals[0][0]))

    # Check the gaps between merged intervals
    for i in range(len(merged_intervals) - 1):
        start_gap = merged_intervals[i][1]
        end_gap = merged_intervals[i + 1][0]

        if start_gap < end_gap:
            uncovered_gaps.append((start_gap, end_gap))

    # Check the gap between the upper bound of the max range and the last interval
    if merged_intervals and merged_intervals[-1][1] < max(max_range):
        uncovered_gaps.append((merged_intervals[-1][1], max(max_range)))

    return uncovered_gaps


class DB:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def close(self) -> None:
        self.conn.close()

    @classmethod
    def create_db(cls, db_path: Path) -> "DB":
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS process_log (
                    timestamp TEXT, source_file TEXT, output_file TEXT, start_time TEXT, end_time TEXT, status TEXT
                )"""
            )
        return cls(conn)

    def log_status(
        self,
        source_file: Path,
        output_file: Path | None,
        time_range: TimeRange,
        status: str,
    ) -> None:
        start, end = time_range
        self.conn.execute(
            """INSERT INTO process_log (timestamp, source_file, output_file, start_time, end_time, status)
            VALUES (strftime('%Y-%m-%d %H-%M-%f','now'), :source_file, :output_file, :start, :end, :status)""",
            dict(
                source_file=source_file.as_posix(),
                output_file=output_file.as_posix() if output_file else None,
                start=str(start),
                end=str(end),
                status=status,
            ),
        )
        self.conn.commit()

    def read_ranges(self, source_file: Path, status: str) -> list[TimeRange]:
        cursor = self.conn.execute(
            """SELECT start_time, end_time
            FROM process_log
            WHERE source_file = :source_file AND status = :status
            ORDER BY start_time""",
            dict(source_file=source_file.as_posix(), status=status),
        )
        return [(Decimal(s), Decimal(e)) for (s, e) in cursor.fetchall()]

    def get_merge_order(self, source_file: Path) -> list[Path]:
        cursor = self.conn.execute(
            """SELECT output_file
            FROM process_log
            WHERE source_file = :source_file AND status = 'success'
            ORDER BY start_time ASC""",
            dict(source_file=source_file.as_posix()),
        )
        return [Path(v) for (v,) in cursor.fetchall()]


class EditingTracker:
    def __init__(
        self,
        path: Path,
        video_duration: Decimal,
        split_time: Decimal,
        db: DB,
        split_factor: Decimal = 2,
    ):
        self.path = path
        self.video_duration = video_duration
        self.split_time = split_time
        self.split_factor = split_factor

        self.db = db

    def next(self) -> TimeRange | None:
        current_range = self.current_range()
        if current_range is None:
            return None

        start, range_duration = current_range
        next = min(start + self.split_time, range_duration)

        if attempted_ranges := [
            e for s, e in self.db.read_ranges(self.path, status="failed") if s == start
        ]:
            next = (min(attempted_ranges) + start) / self.split_factor

        return start, next

    def success(self, out_path: Path, completed_range: TimeRange) -> None:
        self.db.log_status(self.path, out_path, completed_range, "success")

    def failed(self, bad_range: TimeRange) -> None:
        self.db.log_status(self.path, None, bad_range, "failed")

    def current_range(self) -> TimeRange | None:
        full_time_range = (Decimal(0), self.video_duration)
        succeeded_ranges = self.db.read_ranges(self.path, status="success")
        uncovered_ranges = find_uncovered_gaps(succeeded_ranges, full_time_range)
        if not uncovered_ranges:
            return None
        return uncovered_ranges[0]

    def done(self) -> bool:
        return self.current_range() is None

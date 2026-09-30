from datetime import date, datetime
from zoneinfo import ZoneInfo

from database_manager import TeslaMateDatabase


def test_local_date_range_is_converted_to_utc():
    database = TeslaMateDatabase.__new__(TeslaMateDatabase)
    database.local_timezone = ZoneInfo("Asia/Shanghai")

    start, end = database._date_range_to_utc(
        date(2026, 7, 25),
        date(2026, 7, 25),
    )

    assert start == datetime(2026, 7, 24, 16, 0)
    assert end == datetime(2026, 7, 25, 16, 0)

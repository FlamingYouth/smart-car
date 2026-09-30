from datetime import datetime, timezone

from database_manager import DriveSummary
from task_scheduler import TeslaTaskScheduler


class FakeWeChat:
    def __init__(self):
        self.messages = []
        self.cards = []

    def send_message(self, *args, **kwargs):
        self.messages.append((args, kwargs))
        return True

    def send_card_message(self, *args, **kwargs):
        self.cards.append((args, kwargs))
        return True


class FakeDatabase:
    def get_cars(self):
        return [
            {"id": 1, "marketing_name": "Car 1", "model": "3"},
            {"id": 2, "marketing_name": "Car 2", "model": "Y"},
        ]

    def get_daily_stats(self, car_id, target_date):
        return {
            "driving": DriveSummary(
                total_distance=10,
                total_duration=20,
                total_consumption=2,
                avg_efficiency=200,
                max_speed=80,
                trip_count=1,
                avg_outside_temp=20,
            ),
            "charging": None,
        }


def test_schedule_reads_notification_switches_and_times():
    scheduler = TeslaTaskScheduler(
        FakeWeChat(),
        FakeDatabase(),
        config={"timezone": "Asia/Shanghai"},
        notification_config={
            "daily_summary": {"enabled": False},
            "weekly_summary": {
                "enabled": True,
                "send_day": 3,
                "send_hour": 18,
            },
            "monthly_summary": {"enabled": False},
        },
    )

    jobs = {job.id: job for job in scheduler.scheduler.get_jobs()}
    assert set(jobs) == {"weekly_summary"}
    assert scheduler.config["weekly_summary_day"] == 3
    assert scheduler.config["weekly_summary_hour"] == 18


def test_daily_summary_sends_one_card_per_car():
    wechat = FakeWeChat()
    scheduler = TeslaTaskScheduler(wechat, FakeDatabase())

    scheduler._send_daily_summary()

    assert len(wechat.cards) == 2
    assert {kwargs["dedup_key"] for _, kwargs in wechat.cards} == {"1", "2"}


def test_trip_completion_uses_local_time_and_car_dedup_key():
    wechat = FakeWeChat()
    scheduler = TeslaTaskScheduler(
        wechat,
        FakeDatabase(),
        config={"timezone": "Asia/Shanghai"},
    )
    trip = {
        "distance": 12.3,
        "duration_min": 30,
        "start_address": "起点",
        "end_address": "终点",
        "start_battery_level": 80,
        "end_battery_level": 70,
        "end_date": datetime(2026, 7, 25, 0, 0, tzinfo=timezone.utc),
    }

    assert scheduler.send_trip_completion_notification("Car 1", trip, car_id="1")

    args, kwargs = wechat.messages[0]
    assert "2026-07-25 08:00:00" in args[1]
    assert kwargs["dedup_key"] == "1"

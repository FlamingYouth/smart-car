#!/usr/bin/env python3
"""调用现有模板生成模拟消息；仅 --send 才访问群机器人，无车辆/DB/MQTT连接。"""

import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
from threading import Event, Lock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402

from database_manager import ChargingSummary, DriveSummary  # noqa: E402
from main import TeslaWeChatNotifier  # noqa: E402
from mqtt_listener import CarState, TeslaMQTTListener  # noqa: E402
from task_scheduler import TeslaTaskScheduler  # noqa: E402
from wechat_client import WeChatClient  # noqa: E402


class Capture:
    def __init__(self):
        self.samples = []
        self.case = ""

    def send_message(self, message_type, content, dedup_key=None):
        self.samples.append(
            {
                "case": self.case,
                "message_type": message_type,
                "content": content,
                "kind": "text",
            }
        )
        return True

    def send_card_message(
        self, message_type, title, description, url=None, dedup_key=None
    ):
        self.samples.append(
            {
                "case": self.case,
                "message_type": message_type,
                "kind": "card",
                "title": title,
                "description": description,
                "url": url,
            }
        )
        return True


class SampleDatabase:
    """纯内存数据，不继承或创建真实数据库连接。"""

    def __init__(self, now):
        self.now = now
        self.detailed_charging = True

    def get_cars(self):
        return [{"id": 1, "model": "3", "marketing_name": "测试车辆（模拟数据）"}]

    def get_latest_completed_charging(self, car_id):
        if not self.detailed_charging:
            return None
        return {
            "start_date": self.now - timedelta(minutes=95),
            "end_date": self.now - timedelta(minutes=5),
            "duration_min": 90,
            "start_battery_level": 35,
            "end_battery_level": 80,
            "charge_energy_added": 28.6,
            "location_name": "测试充电站（模拟）",
            "full_address": "测试充电站（模拟）,测试地址",
        }

    def stats(self, factor=1):
        return {
            "driving": DriveSummary(
                42.6 * factor, 60 * factor, 7.8 * factor, 183.1, 80, 2 * factor, 22.0
            ),
            "charging": ChargingSummary(
                28.6 * factor, 18.0 * factor, factor, 7.0, 90 * factor, 0.5
            ),
        }

    def get_daily_stats(self, car_id, target_date):
        return self.stats()

    def get_weekly_stats(self, car_id, week_start):
        return self.stats(7)

    def get_monthly_stats(self, car_id, year, month):
        return self.stats(30)

    def get_recent_trips(self, car_id, limit):
        return [
            {
                "distance": 21.3,
                "duration_min": 30,
                "start_address": "测试起点（模拟）",
                "end_address": "测试终点（模拟）",
                "start_battery_level": 80,
                "end_battery_level": 75,
                "consumption_kwh": 3.9,
                "end_date": self.now - timedelta(minutes=2),
            }
        ]


class OfflineLifecycle:
    def start(self):
        pass

    def stop(self):
        pass

    def get_job_status(self):
        return []


def generate_samples(now=None, grafana_url="https://grafana.example.com/"):
    now = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    capture = Capture()
    database = SampleDatabase(now)
    scheduler = TeslaTaskScheduler(
        capture,
        database,
        config={"timezone": "Asia/Shanghai", "grafana_url": grafana_url},
    )
    scheduler._today = lambda: now.date()
    listener = TeslaMQTTListener.__new__(TeslaMQTTListener)
    listener.wechat_client = capture
    listener.database = database
    listener.task_scheduler = scheduler
    listener.timezone = ZoneInfo("Asia/Shanghai")
    listener._now = lambda: now
    listener.temp_alert_config = {
        "inside_temp_min": -10,
        "inside_temp_max": 60,
        "outside_temp_min": -30,
        "outside_temp_max": 50,
    }
    listener._state_lock = Lock()
    listener.car_states = {"1": CarState("1", display_name="测试车辆（模拟数据）")}

    notifier = TeslaWeChatNotifier.__new__(TeslaWeChatNotifier)
    notifier.wechat_client = capture
    notifier.database = database
    notifier.mqtt_listener = OfflineLifecycle()
    notifier.task_scheduler = OfflineLifecycle()
    notifier.is_running = False
    notifier.shutdown_event = Event()
    notifier.start_time = None
    notifier.timezone = ZoneInfo("Asia/Shanghai")
    notifier.config = {
        "mqtt": {"host": "模拟MQTT（不连接）", "port": 1883},
        "database": {"host": "模拟数据库（不连接）", "port": 5432},
        "health_check": {"enabled": False},
    }
    # 避免输出样例系统的控制台状态，与通知模板无关。
    notifier._print_system_status = lambda: None
    capture.case = "system_start"
    notifier.start()

    for detailed in (True, False):
        database.detailed_charging = detailed
        for state in ("Complete", "Stopped"):
            capture.case = (
                "charging_" + state.lower() + ("_detailed" if detailed else "_fallback")
            )
            car = CarState(
                "1",
                display_name="测试车辆（模拟数据）",
                battery_level=80,
                previous_charging_state="Charging",
                charging_state=state,
            )
            listener._check_charging_change(car)

    capture.case = "update_available"
    listener._update_car_state("1", "version", "2026.1.0")
    listener._update_car_state("1", "update_available", "true")
    listener._update_car_state("1", "update_version", "2026.2.0")
    for field, value, case in (
        ("inside_temp", "65", "inside_high"),
        ("inside_temp", "-15", "inside_low"),
        ("outside_temp", "55", "outside_high"),
        ("outside_temp", "-35", "outside_low"),
    ):
        capture.case = "temperature_" + case
        listener._update_car_state("1", field, value)

    capture.case = "trip_completed"
    listener._trigger_trip_completion_check(listener.car_states["1"])
    capture.case = "trip_consumption_fallback"
    trip = database.get_recent_trips(1, 1)[0]
    trip["start_battery_level"] = None
    scheduler.send_trip_completion_notification("测试车辆（模拟数据）", trip, "1")
    for message_type in ("daily_summary", "weekly_summary", "monthly_summary"):
        capture.case = message_type
        getattr(scheduler, "_send_" + message_type)()
    capture.case = "system_shutdown"
    notifier.shutdown()
    if len(capture.samples) != 16:
        raise RuntimeError("样例模板生成数量不匹配；未发送")
    return capture.samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--send", action="store_true", help="实际向配置的机器人发送模拟样例"
    )
    parser.add_argument("-c", "--config", default="config.yaml")
    parser.add_argument("--only", help="只测试一个 case 或 message_type")
    args = parser.parse_args()
    try:
        with open(args.config, encoding="utf-8") as file:
            config = yaml.safe_load(file) or {}
        samples = generate_samples(
            grafana_url=config.get("scheduler", {}).get(
                "grafana_url", "https://grafana.example.com/"
            )
        )
        if args.only:
            samples = [
                item
                for item in samples
                if args.only in (item["case"], item["message_type"])
            ]
            if not samples:
                parser.error("--only 未匹配到样例")
        if not args.send:
            print(
                json.dumps(
                    {"mode": "offline-preview", "samples": samples},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        webhook = os.getenv("WECHAT_WEBHOOK_URL", "").strip() or config.get(
            "wechat", {}
        ).get("webhook_url")
        client = WeChatClient(
            webhook,
            {
                item["message_type"]: {
                    "enabled": True,
                    "rate_limit_seconds": 0,
                    "enable_dedup": False,
                }
                for item in samples
            },
        )
        intro = (
            f"🧪 Tesla 通知模板测试：接下来发送 {len(samples)} 条模拟样例。\n"
            "所有车辆、行程、温度、充电和启停信息均为模拟数据；"
            "没有连接或操作真实车辆、数据库和 MQTT。"
        )
        if not client.send_message("sample_intro", intro):
            return 1
        for index, item in enumerate(samples, 1):
            if item["kind"] == "card":
                result = client.send_card_message(
                    item["message_type"],
                    item["title"],
                    item["description"],
                    url=item["url"],
                )
            else:
                result = client.send_message(item["message_type"], item["content"])
            print(
                f"[{index}/{len(samples)}] {item['case']}: {'成功' if result else '失败'}"
            )
            if not result:
                print("已停止后续发送，请检查机器人配置或网络；不会自动重试。")
                return 1
        print(f"完成：{len(samples)} 条样例 + 1 条模拟测试说明，均获接口成功回应。")
        return 0
    except Exception as exc:
        print(f"样例测试失败：{type(exc).__name__}（详情已隐藏，防止泄露密钥）")
        return 1


if __name__ == "__main__":
    sys.exit(main())

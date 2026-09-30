#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定时统计报告与行程完成通知。"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database_manager import ChargingSummary, DriveSummary, TeslaMateDatabase
from wechat_client import WeChatClient

logger = logging.getLogger(__name__)


class TeslaTaskScheduler:
    """Tesla 通知任务调度器。"""

    def __init__(
        self,
        wechat_client: WeChatClient,
        database: TeslaMateDatabase,
        config: Optional[Dict[str, Any]] = None,
        notification_config: Optional[Dict[str, Any]] = None,
    ):
        self.wechat_client = wechat_client
        self.database = database
        config = config or {}
        self.notification_config = notification_config or {}

        self.timezone = ZoneInfo(config.get("timezone", "Asia/Shanghai"))
        self.grafana_url = config.get("grafana_url", "https://grafana.bigbey.com/")
        self.scheduler = BackgroundScheduler(timezone=self.timezone)

        self.config = {
            "daily_summary_hour": 22,
            "weekly_summary_day": 0,
            "weekly_summary_hour": 9,
            "monthly_summary_day": 1,
            "monthly_summary_hour": 9,
        }
        self.config.update(
            {key: value for key, value in config.items() if key in self.config}
        )
        self._apply_notification_schedule()
        self._setup_tasks()

    def _apply_notification_schedule(self) -> None:
        mappings = {
            "daily_summary": {"send_hour": "daily_summary_hour"},
            "weekly_summary": {
                "send_day": "weekly_summary_day",
                "send_hour": "weekly_summary_hour",
            },
            "monthly_summary": {
                "send_day": "monthly_summary_day",
                "send_hour": "monthly_summary_hour",
            },
        }
        for message_type, fields in mappings.items():
            values = self.notification_config.get(message_type, {})
            if not isinstance(values, dict):
                continue
            for source_key, target_key in fields.items():
                if source_key in values:
                    self.config[target_key] = int(values[source_key])

    def _notification_enabled(self, message_type: str) -> bool:
        values = self.notification_config.get(message_type, {})
        if not isinstance(values, dict):
            return True
        return bool(values.get("enabled", True))

    def _setup_tasks(self) -> None:
        """按启用状态和 YAML 时间设置统计任务。"""
        if self._notification_enabled("daily_summary"):
            self.scheduler.add_job(
                func=self._send_daily_summary,
                trigger=CronTrigger(
                    hour=self.config["daily_summary_hour"],
                    minute=0,
                    timezone=self.timezone,
                ),
                id="daily_summary",
                name="每日总结",
                replace_existing=True,
            )

        if self._notification_enabled("weekly_summary"):
            self.scheduler.add_job(
                func=self._send_weekly_summary,
                trigger=CronTrigger(
                    day_of_week=self.config["weekly_summary_day"],
                    hour=self.config["weekly_summary_hour"],
                    minute=0,
                    timezone=self.timezone,
                ),
                id="weekly_summary",
                name="每周总结",
                replace_existing=True,
            )

        if self._notification_enabled("monthly_summary"):
            self.scheduler.add_job(
                func=self._send_monthly_summary,
                trigger=CronTrigger(
                    day=self.config["monthly_summary_day"],
                    hour=self.config["monthly_summary_hour"],
                    minute=0,
                    timezone=self.timezone,
                ),
                id="monthly_summary",
                name="每月总结",
                replace_existing=True,
            )

        logger.info("定时任务设置完成")

    def _today(self) -> date:
        return datetime.now(self.timezone).date()

    def _to_local_time(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(self.timezone)

    @staticmethod
    def _car_name(car: Dict[str, Any]) -> str:
        return car.get("marketing_name") or f"Tesla {car.get('model') or ''}".strip()

    def send_trip_completion_notification(
        self,
        car_name: str,
        trip: Dict[str, Any],
        car_id: Optional[str] = None,
    ) -> bool:
        """发送行程完成通知。"""
        try:
            distance = float(trip.get("distance") or 0)
            duration = int(trip.get("duration_min") or 0)
            consumption = float(trip.get("consumption_kwh") or 0)
            avg_speed = distance / (duration / 60) if duration > 0 else 0
            start_addr = trip.get("start_address") or "未知"
            end_addr = trip.get("end_address") or "未知"
            start_full_addr = trip.get("start_full_address") or start_addr
            end_full_addr = trip.get("end_full_address") or end_addr

            message = f"🏁 {car_name} 行程完成\n"
            message += (
                "📍 起点: "
                f"{self._format_smart_address(start_addr, start_full_addr)}\n"
            )
            message += (
                "📍 终点: " f"{self._format_smart_address(end_addr, end_full_addr)}\n"
            )
            message += f"🛣️ 里程: {distance:.1f} km\n"
            message += f"⏱️ 时长: {self._format_duration(duration)}\n"

            start_battery = int(trip.get("start_battery_level") or 0)
            end_battery_value = trip.get("end_battery_level")
            if start_battery > 0 and end_battery_value is not None:
                end_battery = int(end_battery_value)
                battery_consumed = start_battery - end_battery
                message += (
                    f"🔋 消耗: {battery_consumed}%"
                    f"（{start_battery}%->{end_battery}%）电量\n"
                )
            else:
                message += f"⚡ 消耗: {consumption:.1f} kWh\n"

            message += f"🏇️ 平均时速: {avg_speed:.1f} km/h\n"
            end_time = self._to_local_time(trip["end_date"])
            message += f"🕐 完成时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}"

            return self.wechat_client.send_message(
                "trip_completed",
                message,
                dedup_key=car_id or car_name,
            )
        except Exception:
            logger.exception("发送行程完成通知异常")
            return False

    def _send_daily_summary(self) -> None:
        """发送上一自然日总结。"""
        target_date = self._today() - timedelta(days=1)
        try:
            for car in self.database.get_cars():
                car_id = car["id"]
                car_name = self._car_name(car)
                stats = self.database.get_daily_stats(car_id, target_date)
                driving = stats.get("driving")
                if not driving or driving.trip_count <= 0:
                    continue

                message = self._format_daily_summary(
                    target_date,
                    driving,
                    stats.get("charging"),
                )
                self.wechat_client.send_card_message(
                    "daily_summary",
                    f"📊 {car_name} 昨日总结",
                    message,
                    url=self.grafana_url,
                    dedup_key=str(car_id),
                )
        except Exception:
            logger.exception("发送每日总结异常")

    def _send_weekly_summary(self) -> None:
        """发送上一自然周总结。"""
        today = self._today()
        last_monday = today - timedelta(days=today.weekday() + 7)
        try:
            for car in self.database.get_cars():
                car_id = car["id"]
                car_name = self._car_name(car)
                stats = self.database.get_weekly_stats(car_id, last_monday)
                driving = stats.get("driving")
                if not driving or driving.trip_count <= 0:
                    continue

                message = self._format_weekly_summary(
                    last_monday,
                    driving,
                    stats.get("charging"),
                )
                self.wechat_client.send_card_message(
                    "weekly_summary",
                    f"📈 {car_name} 上周总结",
                    message,
                    url=self.grafana_url,
                    dedup_key=str(car_id),
                )
        except Exception:
            logger.exception("发送每周总结异常")

    def _send_monthly_summary(self) -> None:
        """发送上一自然月总结。"""
        today = self._today()
        if today.month == 1:
            year, month = today.year - 1, 12
        else:
            year, month = today.year, today.month - 1

        try:
            for car in self.database.get_cars():
                car_id = car["id"]
                car_name = self._car_name(car)
                stats = self.database.get_monthly_stats(car_id, year, month)
                driving = stats.get("driving")
                if not driving or driving.trip_count <= 0:
                    continue

                message = self._format_monthly_summary(
                    year,
                    month,
                    driving,
                    stats.get("charging"),
                )
                self.wechat_client.send_card_message(
                    "monthly_summary",
                    f"📊 {car_name} {year}年{month}月总结",
                    message,
                    url=self.grafana_url,
                    dedup_key=str(car_id),
                )
        except Exception:
            logger.exception("发送每月总结异常")

    @staticmethod
    def _format_summary_data(
        driving: DriveSummary,
        charging: Optional[ChargingSummary],
    ) -> str:
        avg_speed = 0.0
        if driving.total_duration > 0:
            avg_speed = driving.total_distance / (driving.total_duration / 60)

        charging_count = charging.charging_sessions if charging else 0
        energy_added = charging.total_energy_added if charging else 0
        return (
            f"🛣️ 行驶次数: {driving.trip_count}次\n"
            f"🔋 充电次数: {charging_count}次\n"
            f"📏 行驶里程: {driving.total_distance:.1f} km\n"
            f"🔌 充入电量: {energy_added:.2f} kWh\n"
            f"🏃 平均车速: {avg_speed:.2f} km/h"
        )

    def _format_daily_summary(
        self,
        target_date: date,
        driving: DriveSummary,
        charging: Optional[ChargingSummary],
    ) -> str:
        header = f"📅 日期: {target_date.strftime('%Y年%m月%d日')}\n\n"
        return header + self._format_summary_data(driving, charging)

    def _format_weekly_summary(
        self,
        week_start: date,
        driving: DriveSummary,
        charging: Optional[ChargingSummary],
    ) -> str:
        week_end = week_start + timedelta(days=6)
        header = (
            f"📅 周期: {week_start.strftime('%m.%d')}"
            f" - {week_end.strftime('%m.%d')}\n\n"
        )
        return header + self._format_summary_data(driving, charging)

    def _format_monthly_summary(
        self,
        year: int,
        month: int,
        driving: DriveSummary,
        charging: Optional[ChargingSummary],
    ) -> str:
        header = f"📅 {year}年{month}月数据总结\n\n"
        return header + self._format_summary_data(driving, charging)

    @staticmethod
    def _format_smart_address(address: str, full_address: Optional[str] = None) -> str:
        if not address or address == "unknown":
            return "未知位置"
        if "（" in address and "）" in address:
            return address

        target = full_address if full_address and full_address != address else address
        parts = [
            part.strip()
            for part in target.split(",")
            if part.strip() and not part.strip().isdigit() and part.strip() != "中国"
        ]
        if len(parts) >= 2:
            return ", ".join(parts[:2])
        if parts:
            return parts[0]
        return address

    @staticmethod
    def _format_duration(minutes: int) -> str:
        if minutes < 60:
            return f"{minutes}分钟"
        hours, mins = divmod(minutes, 60)
        if mins == 0:
            return f"{hours}小时"
        return f"{hours}小时{mins}分钟"

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("任务调度器启动成功")
        else:
            logger.warning("任务调度器已在运行中")

    def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)
            logger.info("任务调度器已停止")

    def get_job_status(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": job.id,
                "name": job.name,
                "next_run_time": getattr(job, "next_run_time", None),
                "trigger": str(job.trigger),
            }
            for job in self.scheduler.get_jobs()
        ]

    def update_config(self, new_config: Dict[str, Any]) -> None:
        """在调度器启动前更新任务时间。"""
        if self.scheduler.running:
            raise RuntimeError("运行中的调度器不能直接更新配置")
        self.config.update(
            {key: value for key, value in new_config.items() if key in self.config}
        )
        self.scheduler.remove_all_jobs()
        self._setup_tasks()

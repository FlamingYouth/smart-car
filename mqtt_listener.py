#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MQTT监听器
监听TeslaMate发布的MQTT消息，并触发相应的微信通知
"""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import paho.mqtt.client as mqtt

from wechat_client import WeChatClient

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class CarState:
    """车辆状态数据"""

    car_id: str
    display_name: str = "Tesla"
    state: str = "unknown"  # online, asleep, charging, etc.
    charging_state: str = "Disconnected"  # Charging, Complete, Stopped, etc.
    battery_level: int = 0
    locked: bool = True
    inside_temp: float = 0.0
    outside_temp: float = 0.0
    sentry_mode: bool = False
    doors_open: bool = False
    windows_open: bool = False
    is_user_present: bool = False
    version: str = ""
    update_available: Optional[bool] = None
    update_version: str = ""
    last_update: datetime = field(default_factory=datetime.now)

    # 用于检测状态变化
    previous_state: str = "unknown"
    previous_charging_state: str = "Disconnected"
    previous_locked: bool = True
    previous_doors_open: bool = False
    previous_user_present: bool = False
    #
    # # 延迟通知机制 - 记录异常状态开始时间
    # doors_open_since: datetime = None  # 车门打开开始时间
    # unlocked_since: datetime = None    # 未锁车开始时间
    # doors_notification_sent: bool = False  # 是否已发送车门通知
    # unlock_notification_sent: bool = False  # 是否已发送锁车通知


class TeslaMQTTListener:
    """Tesla MQTT监听器"""

    def __init__(
        self,
        mqtt_host: str,
        mqtt_port: int,
        mqtt_user: str = None,
        mqtt_password: str = None,
        wechat_client: WeChatClient = None,
        timezone_name: str = "Asia/Shanghai",
    ):
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.mqtt_user = mqtt_user
        self.mqtt_password = mqtt_password
        self.wechat_client = wechat_client
        self.timezone = ZoneInfo(timezone_name)

        # 可选的数据库和任务调度器引用
        self.database = None
        self.task_scheduler = None

        # MQTT客户端（paho-mqtt 2.x 使用新版回调 API，同时兼容 1.x）
        self._callback_api_v2 = hasattr(mqtt, "CallbackAPIVersion")
        if self._callback_api_v2:
            self.mqtt_client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2
            )
        else:
            self.mqtt_client = mqtt.Client()
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.on_disconnect = self._on_disconnect

        if mqtt_user and mqtt_password:
            self.mqtt_client.username_pw_set(mqtt_user, mqtt_password)

        # 车辆状态存储
        self.car_states: Dict[str, CarState] = {}
        self._state_lock = threading.Lock()

        # 温度告警配置
        self.temp_alert_config = {
            "inside_temp_min": -10.0,  # 车内最低温度
            "inside_temp_max": 60.0,  # 车内最高温度
            "outside_temp_min": -30.0,  # 车外最低温度
            "outside_temp_max": 50.0,  # 车外最高温度
        }

        # 运行状态
        self.is_running = False
        self._monitor_thread = None
        self._connected_event = threading.Event()
        self._connection_result_event = threading.Event()
        self._connection_error: Optional[int] = None

    def set_database(self, database):
        """设置数据库引用"""
        self.database = database

    def set_task_scheduler(self, task_scheduler):
        """设置任务调度器引用"""
        self.task_scheduler = task_scheduler

    def _now(self) -> datetime:
        return datetime.now(self.timezone)

    def _to_local_time(self, value: Optional[datetime]) -> Optional[datetime]:
        """把 TeslaMate 的 UTC 时间转换为配置时区。"""
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(self.timezone)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        """MQTT连接回调"""
        code = getattr(reason_code, "value", reason_code)
        if code == 0:
            self._connection_error = None
            self._connected_event.set()
            self._connection_result_event.set()
            logger.info(f"MQTT连接成功: {self.mqtt_host}:{self.mqtt_port}")
            # 订阅所有Tesla相关topics
            topics = [
                "teslamate/cars/+/display_name",
                "teslamate/cars/+/state",
                "teslamate/cars/+/charging_state",
                "teslamate/cars/+/battery_level",
                "teslamate/cars/+/locked",
                "teslamate/cars/+/inside_temp",
                "teslamate/cars/+/outside_temp",
                "teslamate/cars/+/sentry_mode",
                "teslamate/cars/+/doors_open",
                "teslamate/cars/+/windows_open",
                "teslamate/cars/+/is_user_present",
                "teslamate/cars/+/plugged_in",
                "teslamate/cars/+/charge_energy_added",
                "teslamate/cars/+/time_to_full_charge",
                "teslamate/cars/+/version",
                "teslamate/cars/+/update_available",
                "teslamate/cars/+/update_version",
            ]

            for topic in topics:
                client.subscribe(topic)
                logger.debug(f"订阅topic: {topic}")
        else:
            self._connection_error = int(code)
            self._connected_event.clear()
            self._connection_result_event.set()
            logger.error(f"MQTT连接失败, 错误码: {code}")

    def _on_disconnect(self, client, userdata, *callback_args):
        """MQTT断开连接回调"""
        if self._callback_api_v2 and len(callback_args) >= 2:
            reason_code = callback_args[1]
        else:
            reason_code = callback_args[0] if callback_args else "unknown"
        code = getattr(reason_code, "value", reason_code)
        self._connected_event.clear()
        logger.warning(f"MQTT连接断开, 错误码: {code}")

    def _on_message(self, client, userdata, msg):
        """MQTT消息回调"""
        try:
            topic = msg.topic
            payload = msg.payload.decode("utf-8").strip()

            logger.debug(f"收到MQTT消息: {topic} = {payload}")

            # 解析topic获取car_id和字段名
            parts = topic.split("/")
            if len(parts) >= 4 and parts[0] == "teslamate" and parts[1] == "cars":
                car_id = parts[2]
                field = parts[3]

                self._update_car_state(car_id, field, payload)

        except Exception as e:
            logger.error(f"处理MQTT消息异常: {e}")

    def _update_car_state(self, car_id: str, field: str, value: str):
        """更新车辆状态并检查是否需要发送通知"""
        action = None
        with self._state_lock:
            # 获取或创建车辆状态
            if car_id not in self.car_states:
                self.car_states[car_id] = CarState(car_id=car_id)

            car_state = self.car_states[car_id]
            car_state.last_update = self._now()

            # 保存之前的状态用于对比
            if field == "state":
                car_state.previous_state = car_state.state
                car_state.state = value
                action = (self._check_state_change, (car_state,))

            elif field == "charging_state":
                car_state.previous_charging_state = car_state.charging_state
                car_state.charging_state = value
                action = (self._check_charging_change, (car_state,))

            elif field == "locked":
                car_state.previous_locked = car_state.locked
                car_state.locked = value.lower() == "true"
                logger.debug(
                    "车辆 %s 门锁状态更新为 %s",
                    car_state.display_name,
                    car_state.locked,
                )

            elif field == "doors_open":
                car_state.previous_doors_open = car_state.doors_open
                car_state.doors_open = value.lower() == "true"
                logger.debug(
                    "车辆 %s 车门状态更新为 %s",
                    car_state.display_name,
                    car_state.doors_open,
                )

            elif field == "display_name":
                car_state.display_name = value

            elif field == "battery_level":
                try:
                    car_state.battery_level = int(float(value))
                except ValueError:
                    pass

            elif field == "inside_temp":
                try:
                    temp = float(value)
                    car_state.inside_temp = temp
                    action = (
                        self._check_temperature_alert,
                        (car_state, "inside", temp),
                    )
                except ValueError:
                    pass

            elif field == "outside_temp":
                try:
                    temp = float(value)
                    car_state.outside_temp = temp
                    action = (
                        self._check_temperature_alert,
                        (car_state, "outside", temp),
                    )
                except ValueError:
                    pass

            elif field == "sentry_mode":
                car_state.sentry_mode = value.lower() == "true"

            elif field == "windows_open":
                car_state.windows_open = value.lower() == "true"

            elif field == "is_user_present":
                car_state.previous_user_present = car_state.is_user_present
                car_state.is_user_present = value.lower() == "true"

            elif field == "version":
                car_state.version = value

            elif field == "update_available":
                car_state.update_available = value.lower() == "true"
                action = (self._check_software_update, (car_state,))

            elif field == "update_version":
                car_state.update_version = value
                action = (self._check_software_update, (car_state,))

        if action:
            callback, args = action
            callback(*args)

    def _check_state_change(self, car_state: CarState):
        """检查车辆状态变化"""
        if not self.wechat_client:
            return

        if car_state.previous_state != car_state.state:
            if car_state.previous_state == "unknown":
                logger.info(
                    f"车辆 {car_state.display_name} 状态变化: default -> {car_state.state}"
                )
            else:
                logger.info(
                    f"车辆 {car_state.display_name} 状态变化: {car_state.previous_state} -> {car_state.state}"
                )

            if car_state.state == "asleep" and car_state.previous_state in [
                "online",
                "charging",
            ]:
                # 车辆进入休眠
                message = (
                    f"😴 {car_state.display_name} 进入休眠模式\n"
                    f"电量: {car_state.battery_level}%\n"
                    f"时间: {self._now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                # self.wechat_client.send_message("vehicle_asleep", message)
                logger.info(message)

            elif (
                car_state.state in ["online", "charging"]
                and car_state.previous_state == "asleep"
            ):
                # 车辆唤醒
                message = (
                    f"👀 {car_state.display_name} 已唤醒\n"
                    f"当前状态: {car_state.state}\n"
                    f"电量: {car_state.battery_level}%\n"
                    f"时间: {self._now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                # self.wechat_client.send_message("vehicle_awake", message)
                logger.info(message)

            elif car_state.previous_state == "driving" and car_state.state in [
                "online",
                "parked",
            ]:
                # 行程结束，延迟触发行程完成检查，等待数据库更新
                logger.info(
                    f"检测到车辆 {car_state.display_name} 行程结束: {car_state.previous_state} -> {car_state.state}，将在10秒后检查行程完成"
                )
                threading.Timer(
                    10.0, lambda: self._trigger_trip_completion_check(car_state)
                ).start()

            # 记录所有状态变化，便于调试
            logger.debug(
                f"状态变化详情: {car_state.display_name} - {car_state.previous_state} -> {car_state.state}"
            )

    def _check_charging_change(self, car_state: CarState):
        """检查充电状态变化"""
        if not self.wechat_client:
            return

        if car_state.previous_charging_state != car_state.charging_state:
            logger.info(
                f"车辆 {car_state.display_name} 充电状态变化: {car_state.previous_charging_state} -> {car_state.charging_state}"
            )

            if (
                car_state.previous_charging_state == "Charging"
                and car_state.charging_state in ["Complete", "Stopped", "Disconnected"]
            ):
                # 充电结束 - 获取详细信息
                status_text = (
                    "充电完成" if car_state.charging_state == "Complete" else "充电停止"
                )

                # 尝试获取充电详细信息
                if self.database:
                    try:
                        car_id = int(car_state.car_id)
                        charging_info = self.database.get_latest_completed_charging(
                            car_id
                        )
                        if charging_info:
                            # 获取充电数据
                            start_date = charging_info.get("start_date")
                            end_date = charging_info.get("end_date")
                            start_level = charging_info.get("start_battery_level", 0)
                            end_level = charging_info.get("end_battery_level", 0)
                            energy_added = charging_info.get("charge_energy_added", 0)
                            duration_min = charging_info.get("duration_min", 0)
                            location = charging_info.get("location_name") or "未知位置"
                            full_address = charging_info.get("full_address")

                            start_time_fixed = self._to_local_time(start_date)
                            end_time_fixed = self._to_local_time(end_date)

                            # 构建优化后的消息格式
                            message = f"🔌 {car_state.display_name} {status_text}\n"

                            if start_time_fixed:
                                message += f"🕐 开始时间: {start_time_fixed.strftime('%Y-%m-%d %H:%M:%S')}\n"
                            if end_time_fixed:
                                message += f"🕐 结束时间: {end_time_fixed.strftime('%Y-%m-%d %H:%M:%S')}\n"

                            # 格式化充电时长
                            if duration_min >= 60:
                                hours = duration_min // 60
                                minutes = duration_min % 60
                                duration_str = (
                                    f"{hours}时{minutes}分"
                                    if minutes > 0
                                    else f"{hours}时"
                                )
                            else:
                                duration_str = f"{duration_min}分钟"
                            message += f"⏱️ 充电时长: {duration_str}\n"

                            # 充入电量信息
                            if energy_added > 0:
                                message += f"⚡ 充入电量: {energy_added:.1f}kWh（{start_level}% → {end_level}%）\n"

                            # 充电地址 - 使用智能地址格式化
                            formatted_location = self._format_charging_address(
                                location, full_address
                            )
                            message += f"📍 充电地址: {formatted_location}"
                        else:
                            # 如果没有获取到详细信息，使用简化格式
                            message = f"🔌 {car_state.display_name} {status_text}\n🔋 当前电量: {car_state.battery_level}%\n"
                            message += (
                                "🕐 完成时间: "
                                f"{self._now().strftime('%Y-%m-%d %H:%M:%S')}"
                            )
                    except Exception as e:
                        logger.warning(f"获取充电详细信息失败: {e}")
                        # 错误时使用简化格式
                        message = f"🔌 {car_state.display_name} {status_text}\n🔋 当前电量: {car_state.battery_level}%\n"
                        message += (
                            "🕐 完成时间: "
                            f"{self._now().strftime('%Y-%m-%d %H:%M:%S')}"
                        )
                else:
                    # 没有数据库连接时的简化格式
                    message = f"🔌 {car_state.display_name} {status_text}\n🔋 当前电量: {car_state.battery_level}%\n"
                    message += (
                        "🕐 完成时间: " f"{self._now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                self.wechat_client.send_message(
                    "charging_stopped",
                    message,
                    dedup_key=car_state.car_id,
                )

    def _check_software_update(self, car_state: CarState) -> None:
        """根据 TeslaMate MQTT 状态发送软件更新提醒。"""
        if (
            not self.wechat_client
            or not car_state.update_available
            or not car_state.update_version
        ):
            return

        current_version = car_state.version or "未知"
        message = (
            f"🔄 {car_state.display_name} 软件更新可用\n"
            f"📱 当前版本: {current_version}\n"
            f"🆕 新版本: {car_state.update_version}\n"
            "💡 建议及时更新以获得最新功能和安全补丁"
        )
        self.wechat_client.send_message(
            "update_available",
            message,
            dedup_key=car_state.car_id,
        )

    def _check_temperature_alert(
        self, car_state: CarState, temp_type: str, temperature: float
    ):
        """检查温度告警"""
        if not self.wechat_client:
            return

        alert_triggered = False
        alert_message = ""

        if temp_type == "inside":
            if temperature < self.temp_alert_config["inside_temp_min"]:
                alert_message = f"🥶 {car_state.display_name} 车内温度过低！\n当前温度: {temperature}°C\n⚠️ 请注意电池保护"
                alert_triggered = True
            elif temperature > self.temp_alert_config["inside_temp_max"]:
                alert_message = f"🔥 {car_state.display_name} 车内温度过高！\n当前温度: {temperature}°C\n⚠️ 请及时处理，注意安全"
                alert_triggered = True

        elif temp_type == "outside":
            if temperature < self.temp_alert_config["outside_temp_min"]:
                alert_message = f"❄️ {car_state.display_name} 环境温度极低\n当前温度: {temperature}°C\n💡 建议预热车辆和电池"
                alert_triggered = True
            elif temperature > self.temp_alert_config["outside_temp_max"]:
                alert_message = f"☀️ {car_state.display_name} 环境温度极高\n当前温度: {temperature}°C\n💡 建议预冷车内环境"
                alert_triggered = True

        if alert_triggered:
            alert_message += f"\n时间: {self._now().strftime('%Y-%m-%d %H:%M:%S')}"
            self.wechat_client.send_message(
                "temperature_alert",
                alert_message,
                dedup_key=f"{car_state.car_id}:{temp_type}",
            )

    def start(self):
        """启动MQTT监听"""
        if self.is_running:
            logger.warning("MQTT监听器已在运行中")
            return

        try:
            logger.info("启动MQTT监听器...")
            self._connected_event.clear()
            self._connection_result_event.clear()
            self._connection_error = None
            self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, 60)
            self.mqtt_client.loop_start()
            self.is_running = True

            if not self._connection_result_event.wait(timeout=10):
                self.is_running = False
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
                raise TimeoutError("等待MQTT连接确认超时")

            if not self._connected_event.is_set():
                error = self._connection_error
                self.is_running = False
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
                if error is not None:
                    raise ConnectionError(f"MQTT连接被拒绝，错误码: {error}")
                raise ConnectionError("MQTT连接失败")

            self._monitor_thread = threading.Thread(
                target=self._connection_monitor,
                daemon=True,
            )
            self._monitor_thread.start()

            logger.info("MQTT监听器启动成功")

        except Exception as e:
            logger.error(f"启动MQTT监听器失败: {e}")
            raise

    def stop(self):
        """停止MQTT监听"""
        if not self.is_running:
            return

        logger.info("停止MQTT监听器...")
        self.is_running = False
        self._connected_event.clear()

        try:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        except Exception as e:
            logger.error(f"停止MQTT监听器异常: {e}")

        logger.info("MQTT监听器已停止")

    def _connection_monitor(self):
        """连接监控线程"""
        while self.is_running:
            try:
                if not self.mqtt_client.is_connected():
                    logger.warning("MQTT连接丢失，尝试重连...")
                    self.mqtt_client.reconnect()
                time.sleep(30)  # 每30秒检查一次连接状态
            except Exception as e:
                logger.error(f"MQTT连接监控异常: {e}")
                time.sleep(60)  # 出错时等待更长时间再重试

    def get_car_states(self) -> Dict[str, CarState]:
        """获取所有车辆状态"""
        with self._state_lock:
            return self.car_states.copy()

    def get_car_state(self, car_id: str) -> Optional[CarState]:
        """获取指定车辆状态"""
        with self._state_lock:
            return self.car_states.get(car_id)

    def set_temperature_alert_config(self, config: Dict[str, float]):
        """设置温度告警配置"""
        self.temp_alert_config.update(config)
        logger.info(f"温度告警配置已更新: {self.temp_alert_config}")

    def _trigger_trip_completion_check(self, car_state: CarState):
        """触发行程完成检查"""
        if not self.database or not self.task_scheduler:
            logger.warning(
                f"数据库或任务调度器未设置，无法触发行程完成检查: db={bool(self.database)}, scheduler={bool(self.task_scheduler)}"
            )
            return

        try:
            # 获取车辆ID (从topic解析)
            car_id = int(car_state.car_id)
            logger.info(f"检查车辆 {car_id} ({car_state.display_name}) 的行程完成情况")

            # 获取最近的行程
            recent_trips = self.database.get_recent_trips(
                car_id, 1
            )  # 只获取最新的一次行程
            logger.info(f"找到 {len(recent_trips) if recent_trips else 0} 个最近行程")

            if recent_trips:
                latest_trip = recent_trips[0]
                trip_end_time = latest_trip["end_date"]

                trip_end_time_local = self._to_local_time(trip_end_time)
                time_diff = self._now() - trip_end_time_local

                logger.info(
                    "最新行程结束时间: %s (UTC), %s (本地), 距离现在: %s",
                    trip_end_time,
                    trip_end_time_local,
                    time_diff,
                )

                # 检查行程是否在最近30分钟内完成
                if timedelta(0) <= time_diff < timedelta(minutes=30):
                    logger.info(f"发送行程完成通知: {car_state.display_name}")
                    self.task_scheduler.send_trip_completion_notification(
                        car_state.display_name,
                        latest_trip,
                        car_id=car_state.car_id,
                    )
                else:
                    logger.info(f"行程时间过旧，不发送通知: {time_diff}")
            else:
                logger.warning(f"未找到车辆 {car_id} 的最近行程")

        except Exception as e:
            logger.error(f"触发行程完成检查异常: {e}", exc_info=True)

    def _format_charging_address(self, location: str, full_address: str = None) -> str:
        """智能格式化充电地址显示

        优先使用收藏点名称，否则简化完整地址显示
        例如: 金辉优步花园（出租屋） 保持原样
              天顶街道, 岳麓区, 湘江新区, 岳麓区, 湖南省, 410205, 中国 -> 天顶街道, 岳麓区
        """
        if not location or location == "unknown":
            return "未知位置"

        # 如果包含中文括号，认为是收藏点，保持原样
        if "（" in location and "）" in location:
            return location

        # 使用完整地址信息进行简化
        target_addr = (
            full_address if full_address and full_address != location else location
        )

        # 按逗号分割地址组件
        parts = [part.strip() for part in target_addr.split(",")]

        # 过滤掉邮编和国家
        filtered_parts = []
        for part in parts:
            # 跳过纯数字（邮编）和"中国"
            if part.isdigit() or part == "中国":
                continue
            filtered_parts.append(part)

        # 根据组件数量决定显示方式
        if len(filtered_parts) >= 2:
            return ", ".join(filtered_parts[:2])  # 取前两个
        elif len(filtered_parts) == 1:
            return filtered_parts[0]
        else:
            return location  # 兜底

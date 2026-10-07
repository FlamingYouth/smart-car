#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tesla微信通知系统主程序
集成TeslaMate MQTT监听、数据库查询、企业微信通知等功能
"""

import os
import sys
import signal
import logging
import logging.handlers
import yaml
import time
import threading
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# 导入自定义模块
from wechat_client import WeChatClient
from notification_client import (
    NotificationClient, build_notification_client, channel_enabled,
    notification_sections,
)
from mqtt_listener import TeslaMQTTListener
from database_manager import TeslaMateDatabase
from task_scheduler import TeslaTaskScheduler

# 配置基础日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TeslaWeChatNotifier:
    """Tesla微信通知系统主类"""

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config: Dict[str, Any] = {}

        # 核心组件
        self.wechat_client: Optional[NotificationClient] = None
        self.database: Optional[TeslaMateDatabase] = None
        self.mqtt_listener: Optional[TeslaMQTTListener] = None
        self.task_scheduler: Optional[TeslaTaskScheduler] = None

        # 运行状态
        self.is_running = False
        self.shutdown_event = threading.Event()
        self.start_time: Optional[datetime] = None
        self.timezone = ZoneInfo("Asia/Shanghai")
        self.health_marker_path = Path("/tmp/app_healthy")

        # 加载配置
        self._load_config()

        # 设置日志
        self._setup_logging()

        # 初始化组件
        self._init_components()

        # 设置信号处理
        self._setup_signal_handlers()

    def _load_config(self):
        """加载配置文件"""
        try:
            config_file = Path(self.config_path)
            if not config_file.exists():
                logger.error(f"配置文件不存在: {self.config_path}")
                raise FileNotFoundError(f"配置文件不存在: {self.config_path}")

            with open(config_file, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f)

            # 从环境变量覆盖配置
            self._override_from_env()

            timezone_name = self.config.get("scheduler", {}).get(
                "timezone", "Asia/Shanghai"
            )
            try:
                self.timezone = ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError as exc:
                raise ValueError(f"无效的时区配置: {timezone_name}") from exc

            health_config = self.config.get("health_check", {})
            self.health_marker_path = Path(
                health_config.get("marker_file", "/tmp/app_healthy")
            )

            logger.info(f"配置文件加载成功: {self.config_path}")

        except Exception as e:
            logger.error("加载配置文件失败: type=%s（配置详情已隐藏）", type(e).__name__)
            raise

    def _override_from_env(self):
        """从环境变量覆盖配置"""
        env_mappings = {
            # 企业微信配置
            "WECHAT_WEBHOOK_URL": ["wechat", "webhook_url"],
            # 数据库配置（支持多种环境变量名称）
            "DB_HOST": ["database", "host"],
            "DATABASE_HOST": ["database", "host"],
            "DB_PORT": ["database", "port"],
            "DATABASE_PORT": ["database", "port"],
            "DB_NAME": ["database", "database"],
            "DATABASE_NAME": ["database", "database"],
            "DB_USER": ["database", "user"],
            "DATABASE_USER": ["database", "user"],
            "DB_PASSWORD": ["database", "password"],
            "DATABASE_PASS": ["database", "password"],
            # MQTT配置
            "MQTT_HOST": ["mqtt", "host"],
            "MQTT_PORT": ["mqtt", "port"],
            "MQTT_USER": ["mqtt", "user"],
            "MQTT_PASSWORD": ["mqtt", "password"],
            # 日志配置
            "LOG_LEVEL": ["logging", "level"],
            "LOG_FILE": ["logging", "file"],
            "APP_TIMEZONE": ["scheduler", "timezone"],
        }

        for env_var, config_path in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None:
                if not value.strip():
                    continue
                # 设置嵌套配置
                config_section = self.config
                for key in config_path[:-1]:
                    if key not in config_section:
                        config_section[key] = {}
                    config_section = config_section[key]

                # 类型转换
                if config_path[-1] in ["port"]:
                    value = int(value)
                elif config_path[-1] in ["ssl"]:
                    value = value.lower() in ["true", "1", "yes"]

                config_section[config_path[-1]] = value
                logger.debug("已从环境变量覆盖配置: %s", env_var)

    def _setup_logging(self):
        """设置日志配置"""
        log_config = self.config.get("logging", {})

        # 设置日志级别
        log_level = getattr(logging, log_config.get("level", "INFO").upper())

        # 创建格式化器
        formatter = logging.Formatter(
            log_config.get(
                "format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        )

        # 获取根日志器
        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)

        # 清除默认处理器
        root_logger.handlers.clear()

        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        # 文件处理器
        log_file = log_config.get("file")
        if log_file:
            try:
                log_path = Path(log_file)
                if log_path.parent != Path("."):
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                file_handler = logging.handlers.RotatingFileHandler(
                    log_path,
                    maxBytes=log_config.get("max_bytes", 10485760),  # 10MB
                    backupCount=log_config.get("backup_count", 5),
                    encoding="utf-8",
                )
                file_handler.setFormatter(formatter)
                root_logger.addHandler(file_handler)
                logger.info(f"日志文件: {log_file}")
            except Exception as e:
                logger.warning(f"创建日志文件处理器失败: {e}")

        logger.info(f"日志级别设置为: {log_level}")

    def _init_components(self):
        """初始化各个组件"""
        try:
            # 原组件仍调用同一通知接口；两个渠道各自发送和限流。
            notification_config = self.config.get("notifications", {})
            self.wechat_client = build_notification_client(self.config)
            logger.info("通知渠道初始化完成: %s",
                        ", ".join(self.wechat_client.clients) or "全部关闭")

            # 初始化数据库连接
            db_config = self.config.get("database", {})
            timezone_name = self.config.get("scheduler", {}).get(
                "timezone", "Asia/Shanghai"
            )
            self.database = TeslaMateDatabase(
                host=db_config.get("host", "localhost"),
                port=db_config.get("port", 5432),
                database=db_config.get("database", "teslamate"),
                user=db_config.get("user", "teslamate"),
                password=db_config.get("password", "password"),
                timezone_name=timezone_name,
            )
            logger.info("数据库连接初始化完成")

            # 初始化MQTT监听器
            mqtt_config = self.config.get("mqtt", {})
            self.mqtt_listener = TeslaMQTTListener(
                mqtt_host=mqtt_config.get("host", "localhost"),
                mqtt_port=mqtt_config.get("port", 1883),
                mqtt_user=mqtt_config.get("user"),
                mqtt_password=mqtt_config.get("password"),
                wechat_client=self.wechat_client,
                timezone_name=timezone_name,
            )

            # 设置温度告警配置
            temp_config = self.config.get("temperature_alerts", {})
            if temp_config:
                self.mqtt_listener.set_temperature_alert_config(temp_config)

            logger.info("MQTT监听器初始化完成")

            # 初始化任务调度器
            scheduler_config = self.config.get("scheduler", {})
            self.task_scheduler = TeslaTaskScheduler(
                wechat_client=self.wechat_client,
                database=self.database,
                config=scheduler_config,
                notification_config=notification_config,
            )

            logger.info("任务调度器初始化完成")

            # 设置MQTT监听器的数据库和任务调度器引用
            self.mqtt_listener.set_database(self.database)
            self.mqtt_listener.set_task_scheduler(self.task_scheduler)

        except Exception as e:
            logger.error(f"组件初始化失败: {e}")
            raise

    def _setup_signal_handlers(self):
        """设置信号处理器"""

        def signal_handler(signum, frame):
            signal_name = signal.Signals(signum).name
            logger.info(f"收到信号 {signal_name}，开始优雅关闭...")
            self.shutdown()

        signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
        signal.signal(signal.SIGTERM, signal_handler)  # 终止信号

        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, signal_handler)  # 挂起信号

    def start(self):
        """启动通知系统"""
        if self.is_running:
            logger.warning("系统已在运行中")
            return

        try:
            logger.info("启动Tesla微信通知系统...")
            self._set_health_marker(False)

            # 启动MQTT监听器
            self.mqtt_listener.start()

            # 启动任务调度器
            self.task_scheduler.start()

            self.is_running = True
            self.start_time = datetime.now(self.timezone)
            self._set_health_marker(True)
            logger.info("Tesla微信通知系统启动成功")

            # 所有核心组件就绪后再发送启动通知
            notification_sent = self.wechat_client.send_message(
                "system_start",
                f"🚀 Tesla微信通知系统启动\n"
                f"📅 启动时间: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"🔗 MQTT服务器: {self.config['mqtt']['host']}:{self.config['mqtt']['port']}\n"
                f"🗄️ 数据库: {self.config['database']['host']}\n"
                f"✅ 系统运行正常",
            )
            if not notification_sent:
                logger.warning("系统已启动，但启动通知发送失败")

            # 打印系统状态
            self._print_system_status()

        except Exception as e:
            logger.error(f"启动系统失败: {e}")
            self.shutdown()
            raise

    def shutdown(self):
        """关闭通知系统"""
        if not self.is_running and self.shutdown_event.is_set():
            return

        was_running = self.is_running
        logger.info("正在关闭Tesla微信通知系统...")
        self.is_running = False

        try:
            # 发送关闭通知
            if was_running and self.wechat_client:
                self.wechat_client.send_message(
                    "system_shutdown",
                    f"🛑 Tesla微信通知系统关闭\n"
                    f"📅 关闭时间: {datetime.now(self.timezone).strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"ℹ️ 系统已安全关闭",
                )

            # 关闭MQTT监听器
            if self.mqtt_listener:
                self.mqtt_listener.stop()

            # 关闭任务调度器
            if self.task_scheduler:
                self.task_scheduler.stop()

            logger.info("Tesla微信通知系统已关闭")

        except Exception as e:
            logger.error(f"关闭系统时出错: {e}")
        finally:
            self._set_health_marker(False)
            self.shutdown_event.set()

    def _set_health_marker(self, healthy: bool) -> None:
        """更新 Docker 健康检查标记。"""
        health_config = self.config.get("health_check", {})
        if not health_config.get("enabled", True):
            return
        try:
            if healthy:
                self.health_marker_path.parent.mkdir(parents=True, exist_ok=True)
                self.health_marker_path.write_text(
                    f"{os.getpid()}\n" f"{datetime.now(self.timezone).isoformat()}\n",
                    encoding="utf-8",
                )
            else:
                self.health_marker_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("更新健康检查标记失败: %s", exc)

    def _print_system_status(self):
        """打印系统状态"""
        try:
            # 获取车辆信息
            cars = self.database.get_cars()

            # 获取任务状态
            jobs = self.task_scheduler.get_job_status()

            print("\n" + "=" * 60)
            print("🚗 Tesla微信通知系统状态")
            print("=" * 60)
            print(f"📊 监控车辆数量: {len(cars)}")
            for car in cars:
                car_name = car.get("marketing_name") or f"Tesla {car['model']}"
                print(f"   - {car_name} (ID: {car['id']})")

            print(f"⚡ 定时任务数量: {len(jobs)}")
            for job in jobs:
                next_run = (
                    job["next_run_time"].strftime("%Y-%m-%d %H:%M:%S")
                    if job["next_run_time"]
                    else "未设置"
                )
                print(f"   - {job['name']}: {next_run}")

            print(
                f"🔗 MQTT服务器: {self.config['mqtt']['host']}:{self.config['mqtt']['port']}"
            )
            print(
                f"🗄️ 数据库: {self.config['database']['host']}:{self.config['database']['port']}"
            )
            channels = getattr(self.wechat_client, "clients", {})
            print("📱 通知方式: " + (", ".join(channels) or "全部关闭"))
            print("=" * 60 + "\n")

        except Exception as e:
            logger.error(f"打印系统状态失败: {e}")

    def run(self):
        """运行系统主循环"""
        self.start()

        try:
            # 主循环
            while self.is_running:
                time.sleep(1)

                # 检查是否收到关闭信号
                if self.shutdown_event.is_set():
                    break

        except KeyboardInterrupt:
            logger.info("收到键盘中断信号")
        except Exception as e:
            logger.error(f"运行时异常: {e}")
        finally:
            self.shutdown()

    def get_system_info(self) -> Dict[str, Any]:
        """获取系统信息"""
        try:
            cars = self.database.get_cars() if self.database else []
            car_states = (
                self.mqtt_listener.get_car_states() if self.mqtt_listener else {}
            )
            jobs = self.task_scheduler.get_job_status() if self.task_scheduler else []

            return {
                "running": self.is_running,
                "start_time": (
                    self.start_time.isoformat() if self.start_time else None
                ),
                "cars_count": len(cars),
                "cars": [
                    {
                        "id": car["id"],
                        "name": car.get("marketing_name") or f"Tesla {car['model']}",
                        "model": car["model"],
                        "state": getattr(
                            car_states.get(str(car["id"])),
                            "state",
                            "unknown",
                        ),
                    }
                    for car in cars
                ],
                "jobs_count": len(jobs),
                "jobs": jobs,
                "config": {
                    "mqtt_host": self.config.get("mqtt", {}).get("host"),
                    "db_host": self.config.get("database", {}).get("host"),
                    "wechat_webhook_configured": bool(
                        self.config.get("wechat", {}).get("webhook_url")
                    ),
                },
            }
        except Exception as e:
            logger.error(f"获取系统信息失败: {e}")
            return {"error": str(e)}


def main():
    """主函数"""
    # 检查Python版本
    if sys.version_info < (3, 9):
        print("错误: 需要Python 3.9或更高版本")
        sys.exit(1)

    # 解析命令行参数
    import argparse

    parser = argparse.ArgumentParser(description="Tesla微信通知系统")
    parser.add_argument(
        "-c", "--config", default="config.yaml", help="配置文件路径 (默认: config.yaml)"
    )
    parser.add_argument("--test-wechat", action="store_true", help="测试企业微信连接")
    parser.add_argument("--test-telegram", action="store_true", help="只测试 Telegram 通知")
    parser.add_argument("--test-notifications", action="store_true", help="测试所有启用的通知渠道")
    parser.add_argument("--test-db", action="store_true", help="测试数据库连接")
    parser.add_argument("--test-mqtt", action="store_true", help="测试MQTT连接")

    args = parser.parse_args()

    try:
        # 测试模式 - 单独测试各个组件
        if args.test_wechat:
            print("测试企业微信连接...")
            # 加载配置但不初始化所有组件
            config_file = Path(args.config)
            if not config_file.exists():
                print(f"错误: 配置文件不存在: {args.config}")
                sys.exit(1)

            with open(config_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            wechat_config = notification_sections(config)["wechat"]
            if not channel_enabled(wechat_config, "wechat", True):
                raise ValueError("企业微信渠道已关闭，未发送测试")
            webhook_url = wechat_config.get("webhook_url")

            # 创建企业微信客户端
            client = WeChatClient(
                webhook_url=webhook_url,
                message_configs=config.get("notifications", {}),
            )

            result = client.send_message("test", "🧪 企业微信连接测试消息")
            print(f"测试结果: {'成功' if result else '失败'}")
            if not result:
                sys.exit(1)
            return

        if args.test_telegram or args.test_notifications:
            # 只构造通知客户端，不连接 PostgreSQL、MQTT 或真实车辆。
            with open(args.config, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            client = build_notification_client(
                config, only="telegram" if args.test_telegram else None
            )
            if not client.clients:
                raise ValueError("请求测试的通知渠道已关闭，未发送测试")
            content = (
                "🧪 Telegram 连接测试消息" if args.test_telegram
                else "🧪 Tesla 通知渠道连接测试消息"
            )
            result = client.send_message("test", content)
            for name, success in client.last_results.items():
                print(f"{name}: {'成功' if success else '失败'}")
            if not result:
                sys.exit(1)
            return

        if args.test_db:
            print("测试数据库连接...")
            # 加载配置
            config_file = Path(args.config)
            if not config_file.exists():
                print(f"错误: 配置文件不存在: {args.config}")
                return

            with open(config_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            # 从环境变量覆盖数据库配置
            db_config = config.get("database", {})
            # 支持更多环境变量名称格式
            db_config["host"] = (
                os.getenv("DB_HOST")
                or os.getenv("DATABASE_HOST")
                or db_config.get("host", "localhost")
            )
            db_config["port"] = int(
                os.getenv("DB_PORT")
                or os.getenv("DATABASE_PORT")
                or db_config.get("port", 5432)
            )
            db_config["database"] = (
                os.getenv("DB_NAME")
                or os.getenv("DATABASE_NAME")
                or db_config.get("database", "teslamate")
            )
            db_config["user"] = (
                os.getenv("DB_USER")
                or os.getenv("DATABASE_USER")
                or db_config.get("user", "teslamate")
            )
            db_config["password"] = (
                os.getenv("DB_PASSWORD")
                or os.getenv("DATABASE_PASS")
                or db_config.get("password", "password")
            )

            # 创建数据库连接
            database = TeslaMateDatabase(
                host=db_config["host"],
                port=db_config["port"],
                database=db_config["database"],
                user=db_config["user"],
                password=db_config["password"],
                timezone_name=config.get("scheduler", {}).get(
                    "timezone", "Asia/Shanghai"
                ),
            )

            cars = database.get_cars()
            print(f"测试结果: 成功，找到 {len(cars)} 辆车")
            return

        if args.test_mqtt:
            print("测试MQTT连接...")
            # 加载配置
            config_file = Path(args.config)
            if not config_file.exists():
                print(f"错误: 配置文件不存在: {args.config}")
                return

            with open(config_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            # 从环境变量覆盖MQTT配置
            mqtt_config = config.get("mqtt", {})
            mqtt_config["host"] = os.getenv(
                "MQTT_HOST", mqtt_config.get("host", "localhost")
            )
            mqtt_config["port"] = int(
                os.getenv("MQTT_PORT", mqtt_config.get("port", 1883))
            )
            mqtt_config["user"] = os.getenv("MQTT_USER", mqtt_config.get("user"))
            mqtt_config["password"] = os.getenv(
                "MQTT_PASSWORD", mqtt_config.get("password")
            )

            # 创建MQTT监听器
            mqtt_listener = TeslaMQTTListener(
                mqtt_host=mqtt_config["host"],
                mqtt_port=mqtt_config["port"],
                mqtt_user=mqtt_config["user"],
                mqtt_password=mqtt_config["password"],
                wechat_client=None,
                timezone_name=config.get("scheduler", {}).get(
                    "timezone", "Asia/Shanghai"
                ),
            )

            mqtt_listener.start()
            time.sleep(5)
            mqtt_listener.stop()
            print("测试结果: MQTT连接正常")
            return

        # 正常运行模式 - 创建完整系统实例
        notifier = TeslaWeChatNotifier(args.config)
        notifier.run()

    except Exception as e:
        logger.error("程序异常退出: type=%s（详情已隐藏）", type(e).__name__)
        sys.exit(1)


if __name__ == "__main__":
    main()

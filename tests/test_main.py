from datetime import datetime
from zoneinfo import ZoneInfo
import sys
from unittest.mock import Mock

import pytest
import yaml

from main import TeslaWeChatNotifier, main
from mqtt_listener import CarState


class FakeDatabase:
    def get_cars(self):
        return [{"id": 1, "marketing_name": "Car", "model": "3"}]


class FakeMQTT:
    def get_car_states(self):
        return {"1": CarState("1", state="online")}


class FakeScheduler:
    def get_job_status(self):
        return []


def make_notifier():
    notifier = TeslaWeChatNotifier.__new__(TeslaWeChatNotifier)
    notifier.database = FakeDatabase()
    notifier.mqtt_listener = FakeMQTT()
    notifier.task_scheduler = FakeScheduler()
    notifier.is_running = True
    notifier.start_time = datetime(
        2026,
        7,
        25,
        8,
        0,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )
    notifier.config = {"health_check": {"enabled": True}}
    notifier.timezone = ZoneInfo("Asia/Shanghai")
    return notifier


def test_system_info_reads_dataclass_state():
    info = make_notifier().get_system_info()

    assert info["cars"][0]["state"] == "online"
    assert info["start_time"] == "2026-07-25T08:00:00+08:00"


def test_health_marker_is_created_and_removed(tmp_path):
    notifier = make_notifier()
    notifier.health_marker_path = tmp_path / "app_healthy"

    notifier._set_health_marker(True)
    lines = notifier.health_marker_path.read_text().splitlines()
    assert int(lines[0]) > 0

    notifier._set_health_marker(False)
    assert not notifier.health_marker_path.exists()


def test_blank_environment_does_not_erase_config(monkeypatch):
    notifier = make_notifier()
    notifier.config.update(
        {"wechat": {"webhook_url": "original"}, "database": {"password": "keep"}}
    )
    monkeypatch.setenv("WECHAT_WEBHOOK_URL", " ")
    monkeypatch.setenv("DB_PASSWORD", "")
    monkeypatch.setenv("WECHAT_CORPID", "ignored")
    monkeypatch.setenv("WECHAT_PROXY", "http://unreachable.example:9999")
    notifier._override_from_env()
    assert notifier.config["wechat"] == {"webhook_url": "original"}
    assert notifier.config["database"]["password"] == "keep"
    monkeypatch.setenv("WECHAT_WEBHOOK_URL", "new")
    notifier._override_from_env()
    assert notifier.config["wechat"]["webhook_url"] == "new"


def test_system_info_never_exposes_webhook():
    notifier = make_notifier()
    notifier.config["wechat"] = {"webhook_url": "private-secret"}
    info = notifier.get_system_info()
    assert info["config"]["wechat_webhook_configured"] is True
    assert "private-secret" not in str(info)


@pytest.mark.parametrize("success", [True, False])
def test_wechat_cli_only_tests_notification_without_db_or_mqtt(
    tmp_path, monkeypatch, success
):
    file = tmp_path / "config.yaml"
    file.write_text(yaml.safe_dump({"wechat": {"webhook_url": "configured"}}))
    monkeypatch.setattr(sys, "argv", ["main.py", "-c", str(file), "--test-wechat"])
    monkeypatch.setenv("WECHAT_WEBHOOK_URL", "")
    client = Mock()
    client.send_message.return_value = success
    factory = Mock(return_value=client)
    monkeypatch.setattr("main.WeChatClient", factory)
    blocked = Mock(side_effect=AssertionError("Real services forbidden"))
    monkeypatch.setattr("main.TeslaMateDatabase", blocked)
    monkeypatch.setattr("main.TeslaMQTTListener", blocked)
    monkeypatch.setattr("main.TeslaWeChatNotifier", blocked)
    if success:
        main()
    else:
        with pytest.raises(SystemExit) as caught:
            main()
        assert caught.value.code == 1
    factory.assert_called_once_with(webhook_url="configured", message_configs={})
    client.send_message.assert_called_once_with("test", "🧪 企业微信连接测试消息")
    blocked.assert_not_called()

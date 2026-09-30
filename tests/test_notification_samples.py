from datetime import datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from scripts.send_notification_samples import generate_samples
from wechat_client import WeChatClient


def test_all_active_templates_generated_without_real_services(monkeypatch):
    blocked = Mock(side_effect=AssertionError("Real services forbidden"))
    monkeypatch.setattr("psycopg2.connect", blocked)
    monkeypatch.setattr("paho.mqtt.client.Client.connect", blocked)
    monkeypatch.setattr("requests.Session.post", blocked)
    samples = generate_samples(
        datetime(2026, 10, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    assert len(samples) == 16
    assert {sample["message_type"] for sample in samples} == {
        "system_start",
        "system_shutdown",
        "charging_stopped",
        "update_available",
        "temperature_alert",
        "trip_completed",
        "daily_summary",
        "weekly_summary",
        "monthly_summary",
    }
    assert sum(sample["kind"] == "card" for sample in samples) == 3
    blocked.assert_not_called()
    for sample in samples:
        if sample["message_type"] not in {"system_start", "system_shutdown"}:
            assert "模拟" in sample.get("content", sample.get("title"))


def test_samples_pass_through_real_adapter_with_original_content():
    samples = generate_samples()
    client = WeChatClient(
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key",
        {
            sample["message_type"]: {"rate_limit_seconds": 0, "enable_dedup": False}
            for sample in samples
        },
    )
    response = Mock(status_code=200)
    response.json.return_value = {"errcode": 0}
    client.session.post = Mock(return_value=response)
    for sample in samples:
        if sample["kind"] == "card":
            assert client.send_card_message(
                sample["message_type"],
                sample["title"],
                sample["description"],
                url=sample["url"],
            )
            expected = (
                sample["title"]
                + "\n"
                + sample["description"]
                + "\n\n[查看详情]("
                + sample["url"]
                + ")"
            )
            kind = "markdown"
        else:
            assert client.send_message(sample["message_type"], sample["content"])
            expected, kind = sample["content"], "text"
        assert client.session.post.call_args.kwargs["json"] == {
            "msgtype": kind,
            kind: {"content": expected},
        }
    assert client.session.post.call_count == 16

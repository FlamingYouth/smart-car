"""Synthetic credentials only; no external notification or vehicle services."""

import sys
from unittest.mock import Mock

import pytest
import requests
import yaml

import main as app
from notification_client import (
    NotificationClient, build_notification_client, notification_sections,
)
from scripts.send_notification_samples import generate_samples
from telegram_client import TelegramClient
from wechat_client import WeChatClient

TOKEN = "123456789:synthetic_test_telegram_token_001"
CHAT_ID = "424242"
WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=offline-test"


def response(body=None, status=200):
    result = Mock(status_code=status)
    result.json.return_value = (
        {"ok": True, "result": {"message_id": 1, "chat": {"id": 424242}}}
        if body is None else body
    )
    return result


def telegram(configs=None, proxy=""):
    client = TelegramClient(TOKEN, CHAT_ID, proxy, configs)
    client.session.post = Mock(return_value=response())
    return client


def dual_config(wechat=True, telegram=True):
    return {
        "wechat": {"enabled": wechat, "webhook_url": WEBHOOK},
        "telegram": {
            "enabled": telegram, "bot_token": TOKEN, "chat_id": CHAT_ID,
            "proxy": "",
        },
    }


@pytest.fixture(autouse=True)
def clear_notification_environment(monkeypatch):
    for name in (
        "WECHAT_ENABLED", "WECHAT_WEBHOOK_URL", "TELEGRAM_ENABLED",
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_PROXY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_plain_text_payload_proxy_and_no_environment_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://unreachable.example:9999")
    client = telegram(proxy="socks5h://127.0.0.1:7897")
    assert client.send_message("test", "🧪 原文\n[文字](网址)")
    client.session.post.assert_called_once_with(
        "https://api.telegram.org/bot" + TOKEN + "/sendMessage",
        json={
            "chat_id": CHAT_ID, "text": "🧪 原文\n[文字](网址)",
            "link_preview_options": {"is_disabled": True},
        },
        timeout=(5, 10), allow_redirects=False,
    )
    assert client.session.trust_env is False
    assert client.session.proxies == {
        "http": "socks5h://127.0.0.1:7897", "https": "socks5h://127.0.0.1:7897",
    }
    assert telegram().session.proxies == {}


@pytest.mark.parametrize("value", ["", None, "not-a-token", TOKEN + "/evil", TOKEN + "\npath"])
def test_invalid_token_error_does_not_echo_credentials(value):
    with pytest.raises(ValueError) as caught:
        TelegramClient(value, CHAT_ID)
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize("value", ["", None, 0, True, "@private_username", "424242/evil"])
def test_private_chat_requires_numeric_nonzero_id(value):
    with pytest.raises(ValueError):
        TelegramClient(TOKEN, value)


def test_negative_group_id_is_supported():
    client = TelegramClient(TOKEN, "-100424242")
    assert client._chat_id == "-100424242"


@pytest.mark.parametrize("proxy", [
    "ftp://proxy:21", "socks5h://proxy", "http://proxy:0",
    "http://proxy:65536", "http://proxy:bad", "http://proxy:7897/path",
    "http://proxy:7897?token=secret", "http://proxy:7897\nunsafe",
])
def test_proxy_validation_rejects_invalid_values_without_echo(proxy):
    with pytest.raises(ValueError) as caught:
        TelegramClient(TOKEN, CHAT_ID, proxy)
    assert proxy not in str(caught.value)


@pytest.mark.parametrize("body", [
    {}, [], {"ok": "true"}, {"ok": False, "description": TOKEN},
    {"ok": True}, {"ok": True, "result": True},
    {"ok": True, "result": {"message_id": True, "chat": {"id": 424242}}},
    {"ok": True, "result": {"message_id": 1, "chat": {"id": 999999}}},
])
def test_only_valid_confirmed_telegram_message_is_success(body, caplog):
    client = telegram()
    client.session.post.return_value = response(body)
    assert not client.send_message("trip_completed", "test", dedup_key="1")
    assert client.get_message_stats()["message_history_count"] == 0
    assert client.get_message_stats()["pending_messages_count"] == 0
    assert TOKEN not in caplog.text


@pytest.mark.parametrize("status", [201, 302, 400, 403, 429, 500])
def test_http_failure_has_no_redirect_or_retry(status):
    client = telegram()
    client.session.post.return_value = response(status=status)
    assert not client.send_message("test", "test")
    assert client.session.post.call_count == 1
    assert client.session.post.call_args.kwargs["allow_redirects"] is False
    client.session.post.return_value.json.assert_not_called()


@pytest.mark.parametrize("error", [requests.Timeout(TOKEN), ValueError(TOKEN)])
def test_network_and_json_errors_are_redacted(error, caplog):
    client = telegram()
    if isinstance(error, requests.Timeout):
        client.session.post.side_effect = error
    else:
        client.session.post.return_value.json.side_effect = error
    assert not client.send_message("test", "test")
    assert TOKEN not in caplog.text


def test_unicode_segments_and_plain_report_preserve_original_text(monkeypatch):
    monkeypatch.setattr("telegram_client.time.sleep", lambda delay: None)
    client = telegram()
    body = "🧪 原文\n" * 1000
    assert client.send_card_message(
        "daily_summary", "原始标题", body, "https://grafana.example.com/", dedup_key="1"
    )
    chunks = [c.kwargs["json"]["text"] for c in client.session.post.call_args_list]
    assert len(chunks) > 1
    assert all(len(c.encode("utf-8")) <= 4096 for c in chunks)
    assert "".join(chunks) == "原始标题\n" + body + "\n\n查看详情：https://grafana.example.com/"
    assert client.send_card_message(
        "daily_summary", "原始标题", body, "https://grafana.example.com/", dedup_key="1"
    )
    assert client.session.post.call_count == len(chunks)


def test_telegram_attempts_are_paced_without_automatic_retry(monkeypatch):
    clock = [100.0]
    sleeps = []
    monkeypatch.setattr("telegram_client.time.monotonic", lambda: clock[0])
    def sleep(delay):
        sleeps.append(delay)
        clock[0] += delay
    monkeypatch.setattr("telegram_client.time.sleep", sleep)
    client = telegram()
    client.session.post.return_value = response(status=429)
    assert not client.send_message("test", "one")
    client.session.post.return_value = response()
    assert client.send_message("test", "two")
    assert sleeps == [pytest.approx(1.1)]
    assert client.session.post.call_count == 2


@pytest.mark.parametrize("wc,tg,expected", [
    (True, True, {"wechat", "telegram"}), (True, False, {"wechat"}),
    (False, True, {"telegram"}), (False, False, set()),
])
def test_yaml_channel_switch_combinations_and_disabled_credentials(wc, tg, expected):
    config = dual_config(wc, tg)
    if not wc:
        config["wechat"]["webhook_url"] = None
    if not tg:
        config["telegram"]["bot_token"] = None
        config["telegram"]["chat_id"] = None
        config["telegram"]["proxy"] = "invalid-unused-proxy"
    assert set(build_notification_client(config).clients) == expected


def test_old_wechat_only_config_keeps_legacy_default():
    client = build_notification_client({"wechat": {"webhook_url": WEBHOOK}})
    assert set(client.clients) == {"wechat"}


def test_environment_override_and_blank_environment_preserve_yaml(monkeypatch):
    config = dual_config()
    monkeypatch.setenv("WECHAT_ENABLED", "false")
    monkeypatch.setenv("TELEGRAM_ENABLED", "TRUE")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", " ")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", " ")
    monkeypatch.setenv("TELEGRAM_PROXY", "socks5h://proxy.example:7897")
    client = build_notification_client(config)
    assert set(client.clients) == {"telegram"}
    assert client.clients["telegram"]._chat_id == CHAT_ID
    assert client.clients["telegram"].session.proxies["https"] == "socks5h://proxy.example:7897"
    assert config["wechat"]["enabled"] is True
    assert notification_sections(config)["telegram"]["bot_token"] == TOKEN


@pytest.mark.parametrize("section", ["wechat", "telegram"])
def test_quoted_yaml_switch_is_rejected(section):
    config = dual_config()
    config[section]["enabled"] = "false"
    with pytest.raises(ValueError):
        build_notification_client(config)


@pytest.mark.parametrize("first_result", [False, RuntimeError(TOKEN)])
def test_one_channel_failure_still_attempts_the_other(first_result, caplog):
    first, second = Mock(), Mock()
    if isinstance(first_result, Exception):
        first.send_message.side_effect = first_result
    else:
        first.send_message.return_value = first_result
    second.send_message.return_value = True
    client = NotificationClient({"wechat": first, "telegram": second})
    assert not client.send_message("test", "original", dedup_key="1")
    second.send_message.assert_called_once_with("test", "original", dedup_key="1")
    assert client.last_results == {"wechat": False, "telegram": True}
    assert TOKEN not in caplog.text


def test_channel_failure_does_not_duplicate_successful_channel_on_manual_retry():
    wc = WeChatClient(WEBHOOK)
    wc.session.post = Mock(return_value=response({"errcode": 45009}))
    tg = telegram()
    client = NotificationClient({"wechat": wc, "telegram": tg})
    assert not client.send_message("trip_completed", "original", dedup_key="1")
    wc.session.post.return_value = response({"errcode": 0})
    assert client.send_message("trip_completed", "original", dedup_key="1")
    assert wc.session.post.call_count == 2
    assert tg.session.post.call_count == 1


def test_all_16_original_samples_reach_both_channels_with_identical_content(monkeypatch):
    monkeypatch.setattr("telegram_client.time.sleep", lambda delay: None)
    samples = generate_samples()
    configs = {
        item["message_type"]: {"rate_limit_seconds": 0, "enable_dedup": False}
        for item in samples
    }
    wc = WeChatClient(WEBHOOK, configs)
    wc.session.post = Mock(return_value=response({"errcode": 0}))
    tg = telegram(configs)
    client = NotificationClient({"wechat": wc, "telegram": tg})
    for item in samples:
        if item["kind"] == "card":
            assert client.send_card_message(
                item["message_type"], item["title"], item["description"], item["url"]
            )
            expected = item["title"] + "\n" + item["description"] + "\n\n查看详情：" + item["url"]
        else:
            assert client.send_message(item["message_type"], item["content"])
            expected = item["content"]
        assert wc.session.post.call_args.kwargs["json"]["text"]["content"] == expected
        assert tg.session.post.call_args.kwargs["json"]["text"] == expected
    assert wc.session.post.call_count == tg.session.post.call_count == 16


@pytest.mark.parametrize("flag", ["--test-telegram", "--test-notifications"])
@pytest.mark.parametrize("success", [True, False])
def test_new_cli_only_sends_notifications_without_real_services(
    tmp_path, monkeypatch, flag, success
):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(dual_config(False, True)))
    monkeypatch.setattr(sys, "argv", ["main.py", "-c", str(path), flag])
    router = NotificationClient({"telegram": Mock()})
    router.clients["telegram"].send_message.return_value = success
    monkeypatch.setattr(app, "build_notification_client", Mock(return_value=router))
    blocked = Mock(side_effect=AssertionError("Real services forbidden"))
    for name in ("TeslaMateDatabase", "TeslaMQTTListener", "TeslaWeChatNotifier"):
        monkeypatch.setattr(app, name, blocked)
    if success:
        app.main()
    else:
        with pytest.raises(SystemExit) as caught:
            app.main()
        assert caught.value.code == 1
    blocked.assert_not_called()


def test_original_mqtt_and_scheduler_receive_same_dual_channel_adapter(monkeypatch):
    db, mqtt, scheduler = Mock(), Mock(), Mock()
    db_factory, mqtt_factory, scheduler_factory = (
        Mock(return_value=db), Mock(return_value=mqtt), Mock(return_value=scheduler)
    )
    monkeypatch.setattr(app, "TeslaMateDatabase", db_factory)
    monkeypatch.setattr(app, "TeslaMQTTListener", mqtt_factory)
    monkeypatch.setattr(app, "TeslaTaskScheduler", scheduler_factory)
    notifier = app.TeslaWeChatNotifier.__new__(app.TeslaWeChatNotifier)
    notifier.config = dual_config()
    notifier.config["scheduler"] = {"timezone": "Asia/Shanghai"}
    notifier._init_components()
    assert set(notifier.wechat_client.clients) == {"wechat", "telegram"}
    assert mqtt_factory.call_args.kwargs["wechat_client"] is notifier.wechat_client
    assert scheduler_factory.call_args.kwargs["wechat_client"] is notifier.wechat_client
    mqtt.set_database.assert_called_once_with(db)
    mqtt.set_task_scheduler.assert_called_once_with(scheduler)

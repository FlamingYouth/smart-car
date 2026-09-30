from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event
from unittest.mock import Mock

import pytest
import requests

from wechat_client import WeChatClient

WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key"


def api_response(payload=None, status=200):
    response = Mock(status_code=status)
    response.json.return_value = {"errcode": 0} if payload is None else payload
    return response


def make_client(configs=None):
    client = WeChatClient(WEBHOOK, configs)
    client.session.post = Mock(return_value=api_response())
    client.session.get = Mock(
        side_effect=AssertionError("No application token requests")
    )
    return client


def test_exact_text_payload_and_no_proxy(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://unreachable.example:9999")
    client = make_client()
    content = "🧪 原文\n换行"
    assert client.send_message("test", content)
    client.session.post.assert_called_once_with(
        WEBHOOK,
        json={"msgtype": "text", "text": {"content": content}},
        timeout=(5, 10),
        allow_redirects=False,
    )
    assert client.session.trust_env is False
    client.session.get.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        " ",
        "http://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k",
        "https://evil.example/cgi-bin/webhook/send?key=k",
        "https://qyapi.weixin.qq.com.evil.example/cgi-bin/webhook/send?key=k",
        "https://user:pass@qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k",
        "https://qyapi.weixin.qq.com:8443/cgi-bin/webhook/send?key=k",
        "https://qyapi.weixin.qq.com:bad/cgi-bin/webhook/send?key=k",
        "https://qyapi.weixin.qq.com/cgi-bin/message/send?key=k",
        WEBHOOK + "#fragment",
        WEBHOOK + "&access_token=secret",
        WEBHOOK + "&key=other",
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=",
        WEBHOOK + "%0A",
        WEBHOOK + "\nunsafe",
    ],
)
def test_invalid_webhook_rejected_without_exposing_url(url):
    with pytest.raises(ValueError) as caught:
        WeChatClient(url)
    assert "test-key" not in str(caught.value)
    assert "evil.example" not in str(caught.value)


def test_explicit_https_default_port_and_whitespace():
    assert (
        WeChatClient(
            "  " + WEBHOOK.replace(".com/", ".com:443/") + " "
        ).session.trust_env
        is False
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        "invalid",
        {"errcode": "0"},
        {"errcode": False},
        {"errcode": None},
        {"errcode": 40014},
        {"errcode": 45009},
    ],
)
def test_only_integer_zero_api_result_is_success(payload):
    client = make_client()
    client.session.post.return_value = api_response(payload)
    assert not client.send_message("trip_completed", "trip", dedup_key="1")
    assert client.session.post.call_count == 1
    assert client.get_message_stats()["message_history_count"] == 0


@pytest.mark.parametrize("status", [201, 301, 302, 400, 403, 429, 500, 503])
def test_non_200_http_is_failure_without_redirect(status):
    client = make_client()
    client.session.post.return_value = api_response(status=status)
    assert not client.send_message("trip_completed", "trip", dedup_key="1")
    assert client.session.post.call_args.kwargs["allow_redirects"] is False
    client.session.post.return_value.json.assert_not_called()


def test_invalid_json_and_connection_failure_are_redacted(caplog):
    client = make_client()
    client.session.post.return_value.json.side_effect = ValueError(WEBHOOK)
    assert not client.send_message("test", "text")
    client.session.post.side_effect = requests.ConnectionError(WEBHOOK)
    assert not client.send_message("test", "text")
    assert "test-key" not in caplog.text
    assert WEBHOOK not in caplog.text


def test_api_error_body_is_not_logged(caplog):
    client = make_client()
    client.session.post.return_value = api_response(
        {"errcode": 40014, "errmsg": WEBHOOK}
    )
    assert not client.send_message("test", "text")
    assert "test-key" not in caplog.text


def test_failed_send_does_not_poison_rate_limit():
    client = make_client()
    client.session.post.side_effect = [api_response({"errcode": 45009}), api_response()]
    assert not client.send_message("daily_summary", "same report", dedup_key="car-1")
    assert client.send_message("daily_summary", "same report", dedup_key="car-1")
    assert client.session.post.call_count == 2
    assert client.get_message_stats()["pending_messages_count"] == 0


def test_rate_limit_is_independent_for_each_car():
    client = make_client()
    assert client.send_message("daily_summary", "car one", dedup_key="car-1")
    assert client.send_message("daily_summary", "car two", dedup_key="car-2")
    assert client.send_message("daily_summary", "changed", dedup_key="car-1")
    assert client.session.post.call_count == 2


def test_dedup_after_cooldown_and_history_clear():
    client = make_client()
    assert client.send_message("trip_completed", "trip", dedup_key="1")
    client._message_history[("trip_completed", "1")] = datetime.now() - timedelta(
        hours=1
    )
    assert client.send_message("trip_completed", "trip", dedup_key="1")
    assert client.session.post.call_count == 1
    client.clear_message_history("trip_completed")
    assert client.send_message("trip_completed", "trip", dedup_key="1")
    assert client.session.post.call_count == 2
    assert len(client._request_times) == 2


def test_disabled_notification_never_calls_api():
    client = make_client({"temperature_alert": {"enabled": False}})
    assert client.send_message("temperature_alert", "too hot", dedup_key="car-1")
    client.session.post.assert_not_called()


@pytest.mark.parametrize("content", ["", "  ", None])
def test_empty_message_not_sent(content):
    client = make_client()
    assert not client.send_message("test", content)
    client.session.post.assert_not_called()


@pytest.mark.parametrize("limit", [2048, 4096])
def test_unicode_chunks_preserve_every_character_and_newline(limit):
    content = ("🧪 中文测试\n" * 2000) + "结尾"
    chunks = WeChatClient._chunks(content, limit)
    assert "".join(chunks) == content
    assert all(0 < len(chunk.encode("utf-8")) <= limit for chunk in chunks)


def test_text_chunk_payloads_and_partial_failure_not_recorded():
    client = make_client()
    content = "🧪" * 700
    client.session.post.side_effect = [api_response(), api_response({"errcode": 45009})]
    assert not client.send_message("trip_completed", content, dedup_key="1")
    assert client.get_message_stats()["message_history_count"] == 0
    assert client.get_message_stats()["pending_messages_count"] == 0
    sent = [
        call.kwargs["json"]["text"]["content"]
        for call in client.session.post.call_args_list
    ]
    assert "".join(sent) == content


@pytest.mark.parametrize("limit", [2048, 4096])
def test_early_newline_followed_by_full_tail_does_not_overflow(limit):
    content = "\n" + "a" * (limit - 1) + "🧪尾巴"
    chunks = WeChatClient._chunks(content, limit)
    assert "".join(chunks) == content
    assert all(len(chunk.encode("utf-8")) <= limit for chunk in chunks)


@pytest.mark.parametrize(
    "message_type", ["daily_summary", "weekly_summary", "monthly_summary"]
)
def test_summary_uses_plain_text_preserving_title_body_and_detail_url(message_type):
    client = make_client()
    title, body = "📊 车辆 昨日总结", "📅 日期\n\n🛣️ 行驶次数: 2次\n原文"
    assert client.send_card_message(
        message_type, title, body, url="https://grafana.example.com/", dedup_key="1"
    )
    assert client.session.post.call_args.kwargs["json"] == {
        "msgtype": "text",
        "text": {
            "content": title
            + "\n"
            + body
            + "\n\n查看详情：https://grafana.example.com/"
        },
    }


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://user:pass@host/",
        "https://host/\nunsafe",
        "bad",
    ],
)
def test_unsafe_report_url_is_rejected_without_sending(url):
    client = make_client()
    assert not client.send_card_message("test", "title", "body", url=url)
    client.session.post.assert_not_called()


def test_plain_report_without_link():
    client = make_client()
    assert client.send_card_message("test", "title", "body")
    assert (
        client.session.post.call_args.kwargs["json"]["text"]["content"] == "title\nbody"
    )


@pytest.mark.parametrize("url", ["https://host/a(b)", "https://host/?a=1&b=2"])
def test_plain_report_preserves_url_without_markdown_encoding(url):
    client = make_client()
    assert client.send_card_message("test", "title", "body", url=url)
    assert client.session.post.call_args.kwargs["json"] == {
        "msgtype": "text",
        "text": {"content": "title\nbody\n\n查看详情：" + url},
    }


def test_long_plain_report_uses_text_byte_limit_and_preserves_all_content():
    client = make_client()
    title, body, url = "📊 总结", "统计数据\n" * 250, "https://grafana.example.com/"
    assert client.send_card_message("daily_summary", title, body, url=url)
    payloads = [call.kwargs["json"] for call in client.session.post.call_args_list]
    assert len(payloads) > 1
    assert all(payload["msgtype"] == "text" for payload in payloads)
    chunks = [payload["text"]["content"] for payload in payloads]
    assert all(
        len(chunk.encode("utf-8")) <= WeChatClient.TEXT_LIMIT for chunk in chunks
    )
    assert "".join(chunks) == title + "\n" + body + "\n\n查看详情：" + url


def test_robot_minute_quota_counts_failures_and_expires(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("wechat_client.time.monotonic", lambda: clock[0])
    client = make_client()
    client.session.post.return_value = api_response({"errcode": 45009})
    for _ in range(18):
        assert not client.send_message("test", "text")
    assert not client.send_message("test", "text")
    assert client.session.post.call_count == 18
    clock[0] += 60
    client.session.post.return_value = api_response()
    assert client.send_message("test", "text")
    assert client.session.post.call_count == 19


def test_insufficient_quota_rejects_whole_multichunk_message():
    client = make_client()
    for _ in range(17):
        assert client.send_message("test", "text")
    assert not client.send_message("trip_completed", "🧪" * 700, dedup_key="1")
    assert client.session.post.call_count == 17


def test_concurrent_duplicate_only_one_post():
    client = make_client()
    entered, release = Event(), Event()

    def post(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return api_response()

    client.session.post.side_effect = post
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            client.send_message, "trip_completed", "trip", dedup_key="1"
        )
        assert entered.wait(5)
        second = pool.submit(
            client.send_message, "trip_completed", "trip", dedup_key="1"
        )
        assert second.result(timeout=5)
        client.clear_message_history()
        assert client.send_message("trip_completed", "trip", dedup_key="1")
        release.set()
        assert first.result(timeout=5)
    assert client.session.post.call_count == 1


def test_concurrent_unique_sends_respect_global_quota():
    client = make_client()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda value: client.send_message("test", str(value)), range(30))
        )
    assert sum(results) == 18
    assert client.session.post.call_count == 18

"""真实 HTTP 栈的容器内冒烟测试；回环服务，无外部网络或真实凭据。"""

from collections import deque
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import sys
from threading import Thread

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.send_notification_samples import generate_samples  # noqa: E402
from wechat_client import WeChatClient  # noqa: E402
import main as app  # noqa: E402

FAKE_WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=offline-test"
requests_received = []
replies = deque()
get_requests = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers["Content-Length"])
        requests_received.append(json.loads(self.rfile.read(size)))
        status, payload = replies.popleft() if replies else (200, {"errcode": 0})
        self.send_response(status)
        if status == 302:
            self.send_header("Location", "/must-not-follow")
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def do_GET(self):
        get_requests.append(self.path)
        self.send_response(500)
        self.end_headers()

    def log_message(self, *args):
        pass


def make_local_client(*args, **kwargs):
    client = WeChatClient(*args, **kwargs)
    # 仅本测试替换已验证的地址，正式客户端不能配置非官方 HTTP 地址。
    client._webhook_url = local_url
    return client


def forbidden(*args, **kwargs):
    raise AssertionError("No real database/MQTT allowed")


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
local_url = f"http://127.0.0.1:{server.server_port}/fake-webhook"
Thread(target=server.serve_forever, daemon=True).start()
try:
    for variable in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        os.environ[variable] = "http://127.0.0.1:1"
    samples = generate_samples()
    client = make_local_client(
        FAKE_WEBHOOK,
        {
            sample["message_type"]: {"rate_limit_seconds": 0, "enable_dedup": False}
            for sample in samples
        },
    )
    for sample in samples:
        if sample["kind"] == "card":
            assert client.send_card_message(
                sample["message_type"],
                sample["title"],
                sample["description"],
                sample["url"],
            )
        else:
            assert client.send_message(sample["message_type"], sample["content"])
    assert len(requests_received) == 16
    assert sum(item["msgtype"] == "markdown" for item in requests_received) == 3
    assert not get_requests

    # 容器内真实 HTTP 失败处理：403、重定向、API 拒绝，均不自动重试。
    failure_client = make_local_client(FAKE_WEBHOOK)
    for status, payload in (
        (403, {"errcode": 0}),
        (302, {"errcode": 0}),
        (200, {"errcode": 45009}),
        (200, {"unexpected": True}),
    ):
        replies.append((status, payload))
        before = len(requests_received)
        assert not failure_client.send_message("test", "safe test")
        assert len(requests_received) == before + 1
    assert not get_requests

    # 真实 CLI 控制流，只初始化通知客户端，成功/失败状态码正确。
    app.WeChatClient = make_local_client
    app.TeslaMateDatabase = forbidden
    app.TeslaMQTTListener = forbidden
    app.TeslaWeChatNotifier = forbidden
    os.environ["WECHAT_WEBHOOK_URL"] = FAKE_WEBHOOK
    sys.argv = ["main.py", "--test-wechat"]
    app.main()
    replies.append((200, {"errcode": 40014}))
    try:
        app.main()
    except SystemExit as error:
        assert error.code == 1
    else:
        raise AssertionError("Failed test must have a nonzero exit")
    assert not get_requests
    print(
        "Docker HTTP 冒烟通过：16 条模板、4 类拒绝/重定向、CLI 成功/失败及无代理直连。"
    )
finally:
    server.shutdown()
    server.server_close()

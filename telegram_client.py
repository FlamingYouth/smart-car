#!/usr/bin/env python3
"""Telegram 普通文本通知；与企业微信共用消息策略，传输与历史独立。"""

import logging
import re
import time
from urllib.parse import urlsplit

import requests

from wechat_client import WeChatClient

logger = logging.getLogger(__name__)


class TelegramClient(WeChatClient):
    CHANNEL_NAME = "Telegram"
    # Telegram 接口上限为 4096 字符；按 UTF-8 字节保守分段。
    TEXT_LIMIT = 4096
    MIN_INTERVAL_SECONDS = 1.1

    def __init__(self, bot_token, chat_id, proxy="", message_configs=None):
        if not isinstance(bot_token, str) or not re.fullmatch(
            r"[1-9][0-9]{4,11}:[A-Za-z0-9_-]{25,128}", bot_token.strip()
        ):
            raise ValueError("请配置有效的 telegram.bot_token")
        if type(chat_id) not in (str, int) or not re.fullmatch(
            r"-?[0-9]+", str(chat_id).strip()
        ) or int(str(chat_id).strip()) == 0:
            raise ValueError("telegram.chat_id 必须是非零数字 ID；私聊不能用个人用户名")
        self._api_url = "https://api.telegram.org/bot" + bot_token.strip() + "/sendMessage"
        self._chat_id = str(int(str(chat_id).strip()))
        self.session = requests.Session()
        self.session.trust_env = False
        proxy = self._validate_proxy(proxy)
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
        self._last_attempt = None
        self._init_message_state(message_configs)

    @staticmethod
    def _validate_proxy(value):
        if value in ("", None):
            return ""
        error = "telegram.proxy 必须是有效的 HTTP/HTTPS/SOCKS5/SOCKS5H 代理地址"
        if not isinstance(value, str):
            raise ValueError(error)
        value = value.strip()
        if not value:
            return ""
        try:
            parsed = urlsplit(value)
            valid = (
                parsed.scheme in {"http", "https", "socks5", "socks5h"}
                and bool(parsed.hostname)
                and parsed.port is not None
                and 0 < parsed.port <= 65535
                and parsed.path in ("", "/")
                and not parsed.query
                and not parsed.fragment
                and not any(c.isspace() or ord(c) < 32 for c in value)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(error)
        return value

    def _send_chunk(self, chunk, msgtype, index):
        # 父类的请求锁保证同一 Chat ID 的并发发送也按此间隔执行。
        now = time.monotonic()
        if self._last_attempt is not None:
            delay = self.MIN_INTERVAL_SECONDS - (now - self._last_attempt)
            if delay > 0:
                time.sleep(delay)
        self._last_attempt = time.monotonic()
        response = self.session.post(
            self._api_url,
            json={
                "chat_id": self._chat_id,
                "text": chunk,
                "link_preview_options": {"is_disabled": True},
            },
            timeout=(5, 10),
            allow_redirects=False,
        )
        if response.status_code != 200:
            logger.error(
                "Telegram 通知失败: HTTP=%s, 已发送分段=%s",
                response.status_code, index,
            )
            return False
        body = response.json()
        result = body.get("result") if isinstance(body, dict) else None
        if (
            not isinstance(body, dict)
            or body.get("ok") is not True
            or not isinstance(result, dict)
            or type(result.get("message_id")) is not int
            or result["message_id"] <= 0
            or not isinstance(result.get("chat"), dict)
            or type(result["chat"].get("id")) is not int
            or str(result["chat"]["id"]) != self._chat_id
        ):
            code = body.get("error_code") if isinstance(body, dict) else None
            logger.error(
                "Telegram 通知失败: error_code=%s, 已发送分段=%s",
                code if type(code) is int else "无有效结果", index,
            )
            return False
        return True

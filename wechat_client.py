#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""企业微信群机器人客户端；不使用应用凭据或环境代理。"""

import logging
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from threading import Lock
from typing import Any, Dict, Optional, Set, Tuple
from urllib.parse import parse_qs, urlsplit

import requests

logger = logging.getLogger(__name__)


class MessagePriority(Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class MessageConfig:
    priority: MessagePriority
    rate_limit_seconds: int
    enable_dedup: bool = True
    enabled: bool = True


MessageKey = Tuple[str, str]


class WeChatClient:
    """保留按车辆限流、去重；群由 Webhook 决定，不指定应用收件人。"""

    CHANNEL_NAME = "企业微信"
    TEXT_LIMIT = 2048
    MARKDOWN_LIMIT = 4096
    ROBOT_MINUTE_LIMIT = 18

    def __init__(
        self,
        webhook_url: str,
        message_configs: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        self._webhook_url = self._validate_webhook(webhook_url)
        self.session = requests.Session()
        self.session.trust_env = False
        # 底层 DEBUG 请求日志包含 key，不允许输出请求地址。
        logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
        self._init_message_state(message_configs)

    def _init_message_state(self, message_configs=None):
        """两个渠道各自维护原有冷却、去重和请求限额。"""
        self._message_history: Dict[MessageKey, datetime] = {}
        self._last_messages: Dict[MessageKey, str] = {}
        self._pending_messages: Set[MessageKey] = set()
        self._message_lock = Lock()
        self._request_lock = Lock()
        self._request_times = deque()
        defaults = {
            "charging_started": (MessagePriority.NORMAL, 300),
            "charging_stopped": (MessagePriority.NORMAL, 300),
            "vehicle_awake": (MessagePriority.LOW, 900),
            "vehicle_asleep": (MessagePriority.LOW, 900),
            "door_lock_changed": (MessagePriority.HIGH, 60),
            "temperature_alert": (MessagePriority.URGENT, 300),
            "charging_progress": (MessagePriority.LOW, 1800),
            "trip_completed": (MessagePriority.NORMAL, 600),
            "update_available": (MessagePriority.NORMAL, 3600),
            "daily_summary": (MessagePriority.LOW, 86400),
            "weekly_summary": (MessagePriority.LOW, 604800),
            "monthly_summary": (MessagePriority.LOW, 2592000),
            "charging_cost": (MessagePriority.LOW, 604800),
            "battery_health": (MessagePriority.NORMAL, 2592000),
        }
        self._message_configs = {
            name: MessageConfig(priority, seconds)
            for name, (priority, seconds) in defaults.items()
        }
        self.update_message_configs(message_configs or {})

    @staticmethod
    def _validate_webhook(value: str) -> str:
        error = "请配置有效的企业微信群机器人 Webhook（HTTPS 官方发送地址）"
        if not isinstance(value, str) or not value.strip():
            raise ValueError(error)
        value = value.strip()
        try:
            parsed = urlsplit(value)
            query = parse_qs(parsed.query, keep_blank_values=True)
            valid = (
                parsed.scheme == "https"
                and parsed.hostname == "qyapi.weixin.qq.com"
                and parsed.port in (None, 443)
                and parsed.path == "/cgi-bin/webhook/send"
                and not parsed.username
                and not parsed.password
                and not parsed.fragment
                and set(query) == {"key"}
                and len(query["key"]) == 1
                and re.fullmatch(r"[A-Za-z0-9_-]+", query["key"][0])
                and not any(char.isspace() for char in value)
            )
        except (ValueError, KeyError):
            valid = False
        if not valid:
            raise ValueError(error)
        return value

    def update_message_configs(self, configs: Dict[str, Dict[str, Any]]) -> None:
        for message_type, values in configs.items():
            if not isinstance(values, dict):
                continue
            current = self._message_configs.get(
                message_type, MessageConfig(MessagePriority.NORMAL, 300)
            )
            try:
                seconds = max(
                    0, int(values.get("rate_limit_seconds", current.rate_limit_seconds))
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{message_type}.rate_limit_seconds 必须是非负整数"
                ) from exc
            self._message_configs[message_type] = MessageConfig(
                current.priority,
                seconds,
                bool(values.get("enable_dedup", current.enable_dedup)),
                bool(values.get("enabled", current.enabled)),
            )

    @staticmethod
    def _message_key(message_type: str, dedup_key: Optional[str]) -> MessageKey:
        return message_type, str(dedup_key or "global")

    def _reserve_message(self, message_type, content, dedup_key):
        config = self._message_configs.get(message_type)
        if not config:
            return True, None
        if not config.enabled:
            return False, None
        key = self._message_key(message_type, dedup_key)
        with self._message_lock:
            if key in self._pending_messages:
                return False, None
            last = self._message_history.get(key)
            if (
                last
                and (datetime.now() - last).total_seconds() < config.rate_limit_seconds
            ):
                return False, None
            if config.enable_dedup and self._last_messages.get(key) == content:
                return False, None
            self._pending_messages.add(key)
            return True, key

    def _finish_message(self, key, content, success):
        if key is not None:
            with self._message_lock:
                self._pending_messages.discard(key)
                if success:
                    self._message_history[key] = datetime.now()
                    self._last_messages[key] = content

    @staticmethod
    def _chunks(content: str, limit: int):
        """按 UTF-8 字节分段，优先换行边界，不丢字或拆开字符。"""
        chunks, chars, size = [], [], 0
        for char in content:
            char_size = len(char.encode("utf-8"))
            if size + char_size > limit:
                text = "".join(chars)
                boundary = text.rfind("\n") + 1
                if boundary:
                    chunks.append(text[:boundary])
                    chars = list(text[boundary:])
                    size = len(text[boundary:].encode("utf-8"))
                else:
                    chunks.append(text)
                    chars, size = [], 0
                # 早期换行留下的尾段可能仍装不下下一个多字节字符。
                if size + char_size > limit:
                    chunks.append("".join(chars))
                    chars, size = [], 0
            chars.append(char)
            size += char_size
        if chars:
            chunks.append("".join(chars))
        return chunks

    def _send(self, message_type, content, msgtype, dedup_key):
        if not isinstance(content, str) or not content.strip():
            logger.error("消息内容不能为空")
            return False
        allowed, reservation = self._reserve_message(message_type, content, dedup_key)
        if not allowed:
            # 保留旧接口：关闭、限流或去重的跳过不属于传输错误。
            return True
        success = False
        try:
            limit = self.TEXT_LIMIT if msgtype == "text" else self.MARKDOWN_LIMIT
            chunks = self._chunks(content, limit)
            with self._request_lock:
                now = time.monotonic()
                while self._request_times and now - self._request_times[0] >= 60:
                    self._request_times.popleft()
                if len(chunks) + len(self._request_times) > self.ROBOT_MINUTE_LIMIT:
                    logger.warning("机器人分钟限额已达上限，本次未发送；不会标记成功")
                    return False
                for index, chunk in enumerate(chunks):
                    self._request_times.append(time.monotonic())
                    if not self._send_chunk(chunk, msgtype, index):
                        return False
                success = True
                logger.info(
                    "%s通知发送成功: 类型=%s, 分段=%s",
                    self.CHANNEL_NAME, message_type, len(chunks)
                )
                return True
        except Exception as exc:
            # 不输出异常原文、响应正文或 URL，它们可能包含 Webhook 密钥。
            logger.error("%s通知异常: type=%s（未自动重试）",
                         self.CHANNEL_NAME, type(exc).__name__)
            return False
        finally:
            self._finish_message(reservation, content, success)

    def _send_chunk(self, chunk, msgtype, index):
        response = self.session.post(
            self._webhook_url,
            json={"msgtype": msgtype, msgtype: {"content": chunk}},
            timeout=(5, 10),
            allow_redirects=False,
        )
        if response.status_code != 200:
            logger.error(
                "群通知失败: HTTP=%s, 已发送分段=%s",
                response.status_code, index,
            )
            return False
        result = response.json()
        code = result.get("errcode") if isinstance(result, dict) else None
        if type(code) is not int or code != 0:
            logger.error(
                "群通知失败: errcode=%s, 已发送分段=%s",
                code if type(code) is int else "无有效结果", index,
            )
            return False
        return True

    def send_message(
        self, message_type: str, content: str, dedup_key: Optional[str] = None
    ) -> bool:
        return self._send(message_type, content, "text", dedup_key)

    def send_card_message(
        self,
        message_type: str,
        title: str,
        description: str,
        url: Optional[str] = None,
        dedup_key: Optional[str] = None,
    ) -> bool:
        """兼容旧卡片接口：报告以普通文本发送，保留标题、正文和详情网址。"""
        content = f"{title}\n{description}"
        if url:
            try:
                parsed = urlsplit(url)
                if (
                    parsed.scheme not in {"http", "https"}
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                    or any(char.isspace() or ord(char) < 32 for char in url)
                ):
                    raise ValueError("invalid detail link")
            except (ValueError, TypeError):
                logger.error("报告详情链接无效，未发送")
                return False
            content += f"\n\n查看详情：{url}"
        return self._send(message_type, content, "text", dedup_key)

    def get_message_stats(self) -> Dict[str, Any]:
        with self._message_lock:
            return {
                "message_history_count": len(self._message_history),
                "last_messages_count": len(self._last_messages),
                "pending_messages_count": len(self._pending_messages),
                "message_types": list(self._message_configs),
            }

    def clear_message_history(self, message_type: Optional[str] = None) -> None:
        with self._message_lock:
            keys = [
                key
                for key in self._message_history
                if message_type is None or key[0] == message_type
            ]
            for key in keys:
                self._message_history.pop(key, None)
                self._last_messages.pop(key, None)
            # 不清除正在发送的预留，也不重置机器人分钟限额。

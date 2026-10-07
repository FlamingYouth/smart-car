"""为原通知接口分发多个独立渠道，不修改车辆事件或通知模板。"""

import logging
import os

from telegram_client import TelegramClient
from wechat_client import WeChatClient

logger = logging.getLogger(__name__)


def channel_enabled(section, name, default):
    enabled = section.get("enabled", default)
    if type(enabled) is not bool:
        raise ValueError(name + ".enabled 必须使用 YAML 的 true 或 false")
    return enabled


def notification_sections(config):
    sections = {}
    for name in ("wechat", "telegram"):
        section = config.get(name) or {}
        if not isinstance(section, dict):
            raise ValueError(name + " 配置必须是 YAML 字段集合")
        sections[name] = dict(section)
    mappings = {
        "WECHAT_ENABLED": ("wechat", "enabled"),
        "WECHAT_WEBHOOK_URL": ("wechat", "webhook_url"),
        "TELEGRAM_ENABLED": ("telegram", "enabled"),
        "TELEGRAM_BOT_TOKEN": ("telegram", "bot_token"),
        "TELEGRAM_CHAT_ID": ("telegram", "chat_id"),
        "TELEGRAM_PROXY": ("telegram", "proxy"),
    }
    for variable, (name, field) in mappings.items():
        value = os.getenv(variable)
        if value is None or not value.strip():
            continue
        value = value.strip()
        if field == "enabled":
            if value.lower() not in {"true", "false"}:
                raise ValueError(variable + " 必须为 true 或 false")
            value = value.lower() == "true"
        sections[name][field] = value
    return sections


class NotificationClient:
    def __init__(self, clients):
        self.clients = dict(clients)
        self.last_results = {}

    def _dispatch(self, method, *args, **kwargs):
        results = {}
        for name, client in self.clients.items():
            try:
                results[name] = bool(getattr(client, method)(*args, **kwargs))
            except Exception as error:
                # 单个渠道失败后继续其他渠道，不能记录含 Token 的异常原文。
                logger.error("%s 通知异常: type=%s", name, type(error).__name__)
                results[name] = False
        self.last_results = results
        # 两个渠道都关闭时保留旧接口的禁用/跳过语义。
        return all(results.values())

    def send_message(self, message_type, content, dedup_key=None):
        return self._dispatch(
            "send_message", message_type, content, dedup_key=dedup_key
        )

    def send_card_message(self, message_type, title, description, url=None, dedup_key=None):
        return self._dispatch(
            "send_card_message", message_type, title, description,
            url=url, dedup_key=dedup_key,
        )

    def get_message_stats(self):
        return {"channels": {
            name: client.get_message_stats() for name, client in self.clients.items()
        }}

    def clear_message_history(self, message_type=None):
        for client in self.clients.values():
            client.clear_message_history(message_type)


def build_notification_client(config, message_configs=None, only=None):
    sections = notification_sections(config)
    configs = config.get("notifications", {}) if message_configs is None else message_configs
    clients = {}
    wechat = sections["wechat"]
    telegram = sections["telegram"]
    if only in (None, "wechat") and channel_enabled(wechat, "wechat", True):
        clients["wechat"] = WeChatClient(
            webhook_url=wechat.get("webhook_url"), message_configs=configs
        )
    if only in (None, "telegram") and channel_enabled(telegram, "telegram", False):
        clients["telegram"] = TelegramClient(
            bot_token=telegram.get("bot_token"),
            chat_id=telegram.get("chat_id"),
            proxy=telegram.get("proxy", ""),
            message_configs=configs,
        )
    return NotificationClient(clients)

from datetime import datetime, timezone

from mqtt_listener import TeslaMQTTListener


class FakeWeChat:
    def __init__(self):
        self.messages = []

    def send_message(self, *args, **kwargs):
        self.messages.append((args, kwargs))
        return True


def test_lock_and_door_updates_do_not_call_removed_handlers():
    listener = TeslaMQTTListener("localhost", 1883)

    listener._update_car_state("1", "locked", "false")
    listener._update_car_state("1", "doors_open", "true")

    state = listener.get_car_state("1")
    assert state.locked is False
    assert state.doors_open is True


def test_software_update_uses_teslamate_mqtt_fields():
    wechat = FakeWeChat()
    listener = TeslaMQTTListener("localhost", 1883, wechat_client=wechat)

    listener._update_car_state("1", "display_name", "Model 3")
    listener._update_car_state("1", "version", "2026.20")
    listener._update_car_state("1", "update_available", "true")
    assert not wechat.messages

    listener._update_car_state("1", "update_version", "2026.26")

    args, kwargs = wechat.messages[0]
    assert args[0] == "update_available"
    assert "2026.20" in args[1]
    assert "2026.26" in args[1]
    assert kwargs["dedup_key"] == "1"


def test_update_topics_are_subscribed():
    listener = TeslaMQTTListener("localhost", 1883)

    class Client:
        def __init__(self):
            self.topics = []

        def subscribe(self, topic):
            self.topics.append(topic)

    client = Client()
    listener._on_connect(client, None, None, 0)

    assert "teslamate/cars/+/update_available" in client.topics
    assert "teslamate/cars/+/update_version" in client.topics
    assert listener._connected_event.is_set()


def test_utc_database_time_is_converted_to_configured_timezone():
    listener = TeslaMQTTListener(
        "localhost",
        1883,
        timezone_name="Asia/Shanghai",
    )

    converted = listener._to_local_time(
        datetime(2026, 7, 25, 0, 0, tzinfo=timezone.utc)
    )

    assert converted.hour == 8
    assert str(converted.tzinfo) == "Asia/Shanghai"

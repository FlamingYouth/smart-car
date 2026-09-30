"""测试时彻底禁止网络；Docker 另加 --network none 双重隔离。"""

import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def deny(*args, **kwargs):
    raise RuntimeError("Network disabled during tests")


socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.create_connection = deny

import pytest  # noqa: E402

sys.exit(pytest.main(["-q", "-p", "no:cacheprovider", str(Path(__file__).parent)]))

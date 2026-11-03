"""Persistent assignment of one registered robot to one physical Pi."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile


DEFAULT_IDENTITY_FILE = Path(__file__).resolve().parents[1] / "device_identity.json"


def validate_device_id(device_id):
    if not isinstance(device_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", device_id):
        raise ValueError("Device ID can 1..64 ky tu ASCII: chu, so, dau cham, gach ngang/duoi.")


def validate_device_name(name):
    if not isinstance(name, str) or not name.strip() or len(name) > 128:
        raise ValueError("Ten robot can 1..128 ky tu va khong duoc rong.")


@dataclass(frozen=True)
class DeviceIdentity:
    uuid: str
    name: str

    def __post_init__(self):
        validate_device_id(self.uuid)
        validate_device_name(self.name)


def load_identity(path=DEFAULT_IDENTITY_FILE):
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as error:
        raise ValueError(
            f"Chua co dinh danh Pi tai {path}. Chay python wifi_websocket_receiver.py --setup "
            "de gan UUID/ten robot mot lan (them --identity-file neu dung file rieng)."
        ) from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Khong doc duoc cau hinh dinh danh {path}: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"Cau hinh {path} phai la JSON object co uuid va name.")
    return DeviceIdentity(data.get("uuid"), data.get("name"))


def save_identity(path, identity):
    """Replace the config only after a complete UTF-8 document is written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                dir=path.parent, prefix=f".{path.name}.",
                                suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({"uuid": identity.uuid, "name": identity.name}, stream,
                      ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

"""Bounded newline-delimited UTF-8 JSON protocol shared by Pi and laptop."""

from collections import OrderedDict
import hashlib
import json


MAX_FRAME_BYTES = 512 * 1024
ACTIONS = {"upload", "run", "stop", "status", "ping"}


def encode(message):
    return (json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")


class LineDecoder:
    def __init__(self, max_bytes=MAX_FRAME_BYTES):
        self.max_bytes = max_bytes
        self.buffer = bytearray()
        self.discarding = False
        self.dropped = 0

    def feed(self, data):
        frames = []
        for chunk_index, chunk in enumerate(data.split(b"\n")):
            if chunk_index:
                if not self.discarding and self.buffer:
                    frames.append(bytes(self.buffer))
                self.buffer.clear()
                self.discarding = False
            if not self.discarding:
                if len(self.buffer) + len(chunk) > self.max_bytes:
                    self.buffer.clear()
                    self.discarding = True
                    self.dropped += 1
                else:
                    self.buffer.extend(chunk)
        return frames


class RequestHandler:
    def __init__(self, session):
        self.session = session
        self.recent = OrderedDict()

    def handle(self, frame):
        request_id = None
        try:
            request = json.loads(frame.decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("Can JSON object.")
            request_id = request.get("id")
            if not isinstance(request_id, str) or not request_id or len(request_id) > 64:
                request_id = None
                raise ValueError("Can id chuoi 1..64 ky tu.")
            action = request.get("action")
            if not isinstance(action, str) or action not in ACTIONS:
                raise ValueError("Action chua duoc ho tro.")
            if set(request) - {"id", "action", "code"}:
                raise ValueError("Truong du lieu chua duoc ho tro.")
            fingerprint = hashlib.sha256(encode(dict(sorted(request.items())))).digest()
            if request_id in self.recent:
                previous, reply = self.recent[request_id]
                if previous != fingerprint:
                    raise ValueError("ID da duoc dung cho yeu cau khac.")
                return reply
            reply = {"id": request_id, **self.session.dispatch(request)}
            if action not in ("ping", "status"):
                self.recent[request_id] = fingerprint, reply
                if len(self.recent) > 64:
                    self.recent.popitem(last=False)
            return reply
        except (ValueError, UnicodeError, RecursionError) as error:
            return {"id": request_id, "ok": False, "error": str(error)}

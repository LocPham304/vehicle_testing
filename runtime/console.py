"""Shared upload/run console; each transport supplies its own client."""

import json
from pathlib import Path

from vehicle_testing.runtime.paths import DEFAULT_SAMPLE as DEFAULT_FILE


def run_console(client, *, input_fn=input, output_fn=print, default_file=DEFAULT_FILE, prompt="usb> "):
    output_fn("Lenh: upload [duong_dan] | run | stop | status | exit")
    output_fn(f"upload khong kem duong dan se doc: {default_file}")
    while not client.closed:
        try:
            line = input_fn(prompt).strip()
        except EOFError:
            return
        command, _, argument = line.partition(" ")
        if command in ("exit", "thoat"):
            return
        if not command:
            continue
        try:
            if command == "upload":
                path = Path(argument.strip().strip('"')) if argument.strip() else Path(default_file)
                if path.stat().st_size > 65536:
                    raise ValueError("File vuot qua 64 KiB.")
                reply = client.request("upload", code=path.read_text(encoding="utf-8-sig"))
            elif command in ("run", "stop", "status") and not argument.strip():
                reply = client.request(command)
            else:
                output_fn("Dung: upload [file], run, stop, status, exit. Upload KHONG tu run.")
                continue
            output_fn("Pi: " + json.dumps(reply, ensure_ascii=False))
        except (OSError, ValueError, TimeoutError) as error:
            output_fn(str(error))

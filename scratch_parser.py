"""Parse the supported Scratch-generated Python calls as data, never as code."""

import ast
from dataclasses import dataclass
import math


MAX_SOURCE_BYTES = 65536
MAX_EVENTS = 1000
NUMERIC_COMMANDS = {
    "move_forward": "seconds",
    "move_backward": "seconds",
    "turn_left": "degrees",
    "turn_right": "degrees",
}


class ScratchParseError(ValueError):
    def __init__(self, message: str, line: int = 1, column: int = 1):
        self.line = line
        self.column = column
        super().__init__(f"Dong {line}, cot {column}: {message}")


@dataclass(frozen=True)
class BlockMarker:
    block_id: str
    line: int


@dataclass(frozen=True)
class CommandStep:
    command: str
    value: float | str
    unit: str
    block_id: str | None
    line: int


@dataclass(frozen=True)
class ScratchProgram:
    events: tuple[BlockMarker | CommandStep, ...]

    @property
    def marker_count(self) -> int:
        return sum(isinstance(event, BlockMarker) for event in self.events)

    @property
    def command_count(self) -> int:
        return len(self.events) - self.marker_count


def _error(node, message):
    return ScratchParseError(message, node.lineno, node.col_offset + 1)


def parse_program(source: str) -> ScratchProgram:
    """Accept only literal report_block/sendCmd calls in a sequential program."""
    if not isinstance(source, str):
        raise ScratchParseError("Nguon chuong trinh phai la chuoi UTF-8.")
    try:
        size = len(source.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise ScratchParseError("Nguon chuong trinh khong phai UTF-8 hop le.") from error
    if size > MAX_SOURCE_BYTES:
        raise ScratchParseError(f"Chuong trinh vuot qua {MAX_SOURCE_BYTES} byte.")
    try:
        tree = ast.parse(source, mode="exec")
    except (SyntaxError, ValueError, RecursionError) as error:
        raise ScratchParseError(
            f"Cu phap Python khong hop le: {getattr(error, 'msg', str(error))}",
            getattr(error, "lineno", None) or 1, getattr(error, "offset", None) or 1,
        ) from error
    if not tree.body:
        raise ScratchParseError("Chuong trinh rong, khong co block hay lenh.")
    if len(tree.body) > MAX_EVENTS:
        raise ScratchParseError(f"Chuong trinh vuot qua {MAX_EVENTS} buoc.")

    events = []
    current_block = None
    for statement in tree.body:
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            raise _error(statement, "Chi ho tro report_block() va robot.sendCmd() tuan tu.")
        call = statement.value
        marker = isinstance(call.func, ast.Name) and call.func.id == "report_block"
        command = (isinstance(call.func, ast.Attribute) and call.func.attr == "sendCmd"
                   and isinstance(call.func.value, ast.Name) and call.func.value.id == "robot")
        if not (marker or command):
            raise _error(call, "Loi goi ham chua duoc ho tro.")
        if (call.keywords or len(call.args) != 1 or not isinstance(call.args[0], ast.Constant)
                or not isinstance(call.args[0].value, str)):
            raise _error(call, "Moi loi goi can dung mot doi so chuoi co dinh.")
        value = call.args[0].value
        if marker:
            if not value.strip():
                raise _error(call, "Block ID khong duoc rong.")
            current_block = value
            events.append(BlockMarker(value, statement.lineno))
            continue

        name, separator, argument = value.partition(":")
        if not separator:
            raise _error(call, "Lenh phai co dang command:value.")
        if name in NUMERIC_COMMANDS:
            try:
                number = float(argument)
            except (ValueError, OverflowError) as error:
                raise _error(call, f"{name} can tham so so.") from error
            if not math.isfinite(number) or number <= 0:
                raise _error(call, f"{name} can so huu han lon hon 0.")
            events.append(CommandStep(name, number, NUMERIC_COMMANDS[name], current_block, statement.lineno))
        elif name == "led_strip":
            events.append(CommandStep(name, argument, "text", current_block, statement.lineno))
        else:
            raise _error(call, f"Lenh chua duoc ho tro: {name!r}.")
    return ScratchProgram(tuple(events))


def format_program(program: ScratchProgram) -> str:
    """Human-readable preview; IDs/text are escaped for display, not modified."""
    lines = [f"KICH BAN: {program.marker_count} block marker, {program.command_count} lenh (CHI PARSE)."]
    for index, event in enumerate(program.events, start=1):
        prefix = f"[{index:03d}] dong {event.line}"
        if isinstance(event, BlockMarker):
            lines.append(f"{prefix} BLOCK id={event.block_id!r}")
        else:
            value = (f"{event.value:g} {'giay' if event.unit == 'seconds' else 'do'}"
                     if event.unit != "text" else repr(event.value))
            lines.append(f"{prefix} CMD {event.command}: {value}; block={event.block_id!r}")
    return "\n".join(lines)

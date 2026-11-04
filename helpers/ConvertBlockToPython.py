from __future__ import annotations

import argparse
import ast
import io
import math
import tokenize
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class BlockConvertError(ValueError):
    """Code từ FE không hợp lệ."""


@dataclass(frozen=True)
class CommandSpec:
    validate: Callable[[str, str, int], float | str | None]
    resource: str | None = None
    unit: str = ""


@dataclass
class Command:
    name: str            # vd: "move_forward"
    arg: object          # float | str | None, đã ép kiểu
    line: int            # số dòng trong code gốc (để báo lỗi)
    block_id: str | None = None   # chỉ có khi keep_block_ids=True

    @property
    def resource(self) -> str | None:
        return COMMANDS[self.name].resource


@dataclass
class BlockMarker:
    block_id: str
    line: int


MAX_SOURCE_BYTES = 64 * 1024
MAX_STATEMENTS = 1000


# ------------------------------------------------ Bộ kiểm tra tham số
def _number(lo, hi, *, include_lo=True):
    def parse(raw, name, line):
        try:
            v = float(raw.strip())
        except ValueError:
            raise BlockConvertError(f"Dòng {line}: {name} cần một số, nhận {raw!r}")
        above_lower = v >= lo if include_lo else v > lo
        if not math.isfinite(v) or not above_lower or v > hi:
            lower = ">=" if include_lo else ">"
            raise BlockConvertError(f"Dòng {line}: {name} phải {lower} {lo} và <= {hi}")
        return v
    return parse


def _text(max_len):
    def parse(raw, name, line):
        if len(raw) > max_len:
            raise BlockConvertError(f"Dòng {line}: {name} tối đa {max_len} ký tự")
        return raw
    return parse


def _none(raw, name, line):
    if raw.strip():
        raise BlockConvertError(f"Dòng {line}: {name} không có tham số")
    return None


# ---- BẢNG LỆNH TỰ ĐỊNH NGHĨA: thêm block tại một chỗ này.
COMMANDS = {
    "move_forward":  CommandSpec(_number(0, 500, include_lo=False), "motor", "giây"),
    "move_backward": CommandSpec(_number(0, 500, include_lo=False), "motor", "giây"),
    "turn_left":     CommandSpec(_number(0, 360, include_lo=False), "motor", "độ"),
    "turn_right":    CommandSpec(_number(0, 360, include_lo=False), "motor", "độ"),
    # Tay nhận cả 0° và 90°; giá trị ngoài khoảng này bị từ chối.
    "hand_up":       CommandSpec(_number(0, 90, include_lo=True), "hand", "độ, góc tuyệt đối"),
    "hand_down":     CommandSpec(_number(0, 90, include_lo=True), "hand", "độ, góc tuyệt đối"),
    # robot_led_strip và robot_led_strip_hello_world cùng sinh led_strip:<text>.
    "led_strip":     CommandSpec(_text(64), "matrix", "chuỗi"),
    # Generator FE giữ tiền tố robot_ cho bốn lệnh mặt LED, không có tham số.
    "robot_led_matrix_smile":   CommandSpec(_none, "matrix"),
    "robot_led_matrix_cry":     CommandSpec(_none, "matrix"),
    "robot_led_matrix_normal":  CommandSpec(_none, "matrix"),
    "robot_led_matrix_excited": CommandSpec(_none, "matrix"),
    "stop":          CommandSpec(_none),
}


class _ResourceView(Mapping):
    """Mọi giá trị đều lấy trực tiếp từ COMMANDS."""

    def __getitem__(self, name):
        return COMMANDS[name].resource

    def __iter__(self):
        return iter(COMMANDS)

    def __len__(self):
        return len(COMMANDS)


COMMAND_RESOURCES = _ResourceView()


def _strip_call_indentation(source):
    protected_lines = set()
    try:
        wrapped = "(\n" + source + "\n)"
        for token in tokenize.generate_tokens(io.StringIO(wrapped).readline):
            if token.type == tokenize.STRING and token.end[0] > token.start[0]:
                first, last = token.start[0] - 1, token.end[0] - 1
                protected_lines.update(range(first + 1, last + 1))
    except (tokenize.TokenError, IndentationError, SyntaxError) as error:
        line = getattr(error, "lineno", None)
        if line is None and isinstance(error, tokenize.TokenError):
            line = error.args[1][0]
        raise BlockConvertError(f"Dòng {max(1, (line or 2) - 1)}: cú pháp không hợp lệ") from error
    return "\n".join(line if row in protected_lines else line.lstrip(" \t")
                     for row, line in enumerate(source.split("\n"), 1))


def _separate_calls(source):
    """Chèn ';' giữa các lời gọi dính dòng, giữ nguyên chuỗi và số dòng gốc."""
    offsets = [0]
    for line in io.StringIO(source).readlines():
        offsets.append(offsets[-1] + len(line))

    def offset(point):
        return offsets[point[0] - 1] + point[1]

    insertions = []
    previous = None
    depth = 0
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if (depth == 0 and previous is not None and previous.string == ")"
                    and token.type == tokenize.NAME and token.string in ("robot", "report_block")):
                start, end = offset(previous.end), offset(token.start)
                gap = source[start:end].replace("\\\r\n", "").replace("\\\n", "")
                if not gap.strip():
                    insertions.append(start)
            if token.type == tokenize.OP:
                if token.string in ("(", "[", "{"):
                    depth += 1
                elif token.string in (")", "]", "}"):
                    depth -= 1
            previous = token
    except (tokenize.TokenError, IndentationError, SyntaxError) as error:
        line = getattr(error, "lineno", None)
        if line is None and isinstance(error, tokenize.TokenError):
            line = error.args[1][0]
        raise BlockConvertError(f"Dòng {line or 1}: cú pháp không hợp lệ: {error}") from error

    for position in reversed(insertions):
        source = source[:position] + ";" + source[position:]
    return source


def _literal_str(expr, line):
    """Đọc literal chuỗi bằng ast.literal_eval, không thực thi gì."""
    try:
        value = ast.literal_eval(expr)
    except (ValueError, SyntaxError):
        raise BlockConvertError(f"Dòng {line}: cần chuỗi cố định, không dùng biểu thức")
    if not isinstance(value, str):
        raise BlockConvertError(f"Dòng {line}: tham số phải là chuỗi")
    return value


def parse_commands(source: str, keep_block_ids: bool = False) -> list[Command | BlockMarker]:
    """Đọc lệnh; khi giữ ID, marker được giữ thành phần tử riêng theo đúng thứ tự."""
    if not isinstance(source, str):
        raise BlockConvertError("Source phải là chuỗi Python UTF-8.")
    try:
        if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise BlockConvertError(f"Source vượt {MAX_SOURCE_BYTES} byte.")
        source = _strip_call_indentation(source.removeprefix("\ufeff"))
        tree = ast.parse(_separate_calls(source))
    except (SyntaxError, UnicodeError, RecursionError) as error:
        raise BlockConvertError(f"Dòng {getattr(error, 'lineno', 1)}: cú pháp không hợp lệ") from error
    if len(tree.body) > MAX_STATEMENTS:
        raise BlockConvertError(f"Source vượt {MAX_STATEMENTS} câu lệnh.")
    commands = []
    last_block_id = None

    for statement in tree.body:
        line_no = statement.lineno
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            raise BlockConvertError(f"Dòng {line_no}: chỉ nhận report_block() và robot.sendCmd().")
        call = statement.value
        is_report = isinstance(call.func, ast.Name) and call.func.id == "report_block"
        is_send = (isinstance(call.func, ast.Attribute) and call.func.attr == "sendCmd"
                   and isinstance(call.func.value, ast.Name) and call.func.value.id == "robot")
        if not (is_report or is_send):
            raise BlockConvertError(f"Dòng {line_no}: lời gọi không được hỗ trợ.")
        if len(call.args) != 1 or call.keywords:
            raise BlockConvertError(f"Dòng {line_no}: cần đúng một tham số chuỗi.")
        text = _literal_str(call.args[0], line_no)
        if is_report:
            if not text.strip():
                raise BlockConvertError(f"Dòng {line_no}: ID block không được rỗng.")
            if keep_block_ids:
                last_block_id = text
                commands.append(BlockMarker(text, line_no))
            continue
        name, separator, raw_arg = text.partition(":")
        name = name.strip()
        if name not in COMMANDS:
            raise BlockConvertError(f"Dòng {line_no}: lệnh không hỗ trợ: {name!r}")
        spec = COMMANDS[name]
        if not separator and spec.validate is not _none:
            raise BlockConvertError(f"Dòng {line_no}: lệnh phải có dạng tên:giá_trị.")
        arg = spec.validate(raw_arg, name, line_no)
        commands.append(Command(name, arg, line_no, last_block_id))

    return commands


def get_required_resources(commands: list[Command | BlockMarker]) -> tuple[str, ...]:
    """Nhóm thiết bị có trong chương trình, giữ thứ tự xuất hiện và bỏ trùng."""
    return tuple(dict.fromkeys(c.resource for c in commands
                               if isinstance(c, Command) and c.resource is not None))


def to_python(commands: list[Command | BlockMarker]) -> str:
    body = []
    for c in commands:
        if isinstance(c, BlockMarker):
            body.append(f"    robot.report_block({c.block_id!r})")
            continue
        if c.name not in COMMANDS:
            raise BlockConvertError(f"Dòng {c.line}: lệnh không hỗ trợ: {c.name!r}")
        args = "" if c.arg is None else repr(c.arg)   # repr() tự escape chuỗi
        body.append(f"    robot.{c.name}({args})")

    source = "\n".join([
        "from robot_sdk import Robot",
        "",
        f"REQUIRED_RESOURCES = {get_required_resources(commands)!r}",
        "",
        "robot = Robot()",
        "try:",
        *(body or ["    pass"]),
        "finally:",
        "    robot.stop()",
        "",
    ])
    compile(source, "converted_program.py", "exec")
    return source


def convert_block_to_python(source: str, keep_block_ids: bool = False) -> str:
    return to_python(parse_commands(source, keep_block_ids))



class ConvertBlockToPython:
    def convert(self, source: str, keep_block_ids: bool = True) -> str:
        return convert_block_to_python(source, keep_block_ids=keep_block_ids)

    def convert_file(self, input_path: str | Path, output_path: str | Path,
                     keep_block_ids: bool = True) -> Path:
        input_file = Path(input_path)
        output_file = Path(output_path)
        if input_file.resolve() == output_file.resolve():
            raise ValueError("File đầu ra phải khác file đầu vào.")
        source = input_file.read_text(encoding="utf-8-sig")
        result = self.convert(source, keep_block_ids=keep_block_ids)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(result, encoding="utf-8")
        return output_file


def main(argv=None):
    parser = argparse.ArgumentParser(description="Chuyển chuỗi block FE thành Python gọi robot_sdk; không chạy mã.")
    parser.add_argument("--input", required=True, type=Path, help="File chuỗi FE UTF-8")
    parser.add_argument("--output", required=True, type=Path, help="File Python đầu ra")
    parser.add_argument("--drop-block-ids", action="store_true", help="Bỏ các sự kiện report_block")
    args = parser.parse_args(argv)
    try:
        output = ConvertBlockToPython().convert_file(
            args.input, args.output, keep_block_ids=not args.drop_block_ids)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Không chuyển đổi được: {error}\n")
    print(f"Đã sinh Python: {output}; chưa chạy chương trình.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

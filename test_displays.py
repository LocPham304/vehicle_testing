#!/usr/bin/env python3
"""Standalone LED test. Run inside vehicle_testing: python3 test_displays.py.
Scroll HELLO: python3 test_displays.py --target matrix --hello
Enter text: python3 test_displays.py --target matrix --interactive

Defaults are from pi4-source test scripts, not a verified wiring diagram:
TM1637 CLK=BCM16, DIO=BCM6; TM1640 SCLK=BCM7, DIN=BCM5.
Confirm the module power supply and connector pinout before changing wiring.
GPIO7 also belongs to SPI0; it must be free. Run this test on its own.
"""

import argparse
import select
import sys
import time
import unicodedata


DIGITS = (0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F)
MATRIX_OK = (0, 0, 0x3E, 0x41, 0x41, 0x41, 0x3E, 0, 0,
             0x7F, 0x08, 0x14, 0x22, 0x41, 0, 0)

# Five-column, seven-row glyphs. Bit 0 is the top row.
FONT = {
    "A": (0x7E, 0x11, 0x11, 0x11, 0x7E),
    "B": (0x7F, 0x49, 0x49, 0x49, 0x36),
    "C": (0x3E, 0x41, 0x41, 0x41, 0x22),
    "D": (0x7F, 0x41, 0x41, 0x22, 0x1C),
    "E": (0x7F, 0x49, 0x49, 0x49, 0x41),
    "F": (0x7F, 0x09, 0x09, 0x09, 0x01),
    "G": (0x3E, 0x41, 0x49, 0x49, 0x7A),
    "H": (0x7F, 0x08, 0x08, 0x08, 0x7F),
    "I": (0, 0x41, 0x7F, 0x41, 0),
    "J": (0x20, 0x40, 0x41, 0x3F, 0x01),
    "K": (0x7F, 0x08, 0x14, 0x22, 0x41),
    "L": (0x7F, 0x40, 0x40, 0x40, 0x40),
    "M": (0x7F, 0x02, 0x0C, 0x02, 0x7F),
    "N": (0x7F, 0x04, 0x08, 0x10, 0x7F),
    "O": (0x3E, 0x41, 0x41, 0x41, 0x3E),
    "P": (0x7F, 0x09, 0x09, 0x09, 0x06),
    "Q": (0x3E, 0x41, 0x51, 0x21, 0x5E),
    "R": (0x7F, 0x09, 0x19, 0x29, 0x46),
    "S": (0x46, 0x49, 0x49, 0x49, 0x31),
    "T": (0x01, 0x01, 0x7F, 0x01, 0x01),
    "U": (0x3F, 0x40, 0x40, 0x40, 0x3F),
    "V": (0x1F, 0x20, 0x40, 0x20, 0x1F),
    "W": (0x3F, 0x40, 0x38, 0x40, 0x3F),
    "X": (0x63, 0x14, 0x08, 0x14, 0x63),
    "Y": (0x07, 0x08, 0x70, 0x08, 0x07),
    "Z": (0x61, 0x51, 0x49, 0x45, 0x43),
    "0": (0x3E, 0x51, 0x49, 0x45, 0x3E),
    "1": (0, 0x42, 0x7F, 0x40, 0),
    "2": (0x42, 0x61, 0x51, 0x49, 0x46),
    "3": (0x21, 0x41, 0x45, 0x4B, 0x31),
    "4": (0x18, 0x14, 0x12, 0x7F, 0x10),
    "5": (0x27, 0x45, 0x45, 0x45, 0x39),
    "6": (0x3C, 0x4A, 0x49, 0x49, 0x30),
    "7": (0x01, 0x71, 0x09, 0x05, 0x03),
    "8": (0x36, 0x49, 0x49, 0x49, 0x36),
    "9": (0x06, 0x49, 0x49, 0x29, 0x1E),
    " ": (0, 0, 0),
    ".": (0, 0x60, 0x60), ",": (0x40, 0x30),
    "!": (0, 0, 0x5F, 0, 0), "?": (0x02, 0x01, 0x51, 0x09, 0x06),
    "'": (0, 0x03, 0), ":": (0, 0x36, 0x36, 0), ";": (0x40, 0x36),
    "+": (0x08, 0x08, 0x3E, 0x08, 0x08), "-": (0x08, 0x08, 0x08),
    "/": (0x20, 0x10, 0x08, 0x04, 0x02), "=": (0x14, 0x14, 0x14),
    "(": (0, 0x1C, 0x22, 0x41), ")": (0x41, 0x22, 0x1C, 0),
    "_": (0x40, 0x40, 0x40, 0x40, 0x40),
}


def text_columns(text):
    """Return uppercase unaccented text and its columns; reject unknown glyphs."""
    text = text.strip().replace("đ", "d").replace("Đ", "D")
    text = "".join(char for char in unicodedata.normalize("NFD", text)
                   if unicodedata.category(char) != "Mn").upper()
    missing = sorted(set(text) - FONT.keys())
    if missing:
        raise ValueError("Ky tu chua co font: " + " ".join(repr(char) for char in missing))
    columns = []
    for index, char in enumerate(text):
        if index:
            columns.append(0)
        columns.extend(FONT[char])
    return text, columns


def text_frames(columns):
    """Center short text; scroll longer text into and out of a 16x8 frame."""
    if len(columns) <= 16:
        left = (16 - len(columns)) // 2
        yield [0] * left + list(columns) + [0] * (16 - left - len(columns))
        return
    strip = [0] * 16 + list(columns) + [0] * 16
    for offset in range(len(strip) - 16 + 1):
        yield strip[offset:offset + 16]


def hello_frames():
    """Preserve the original HELLO test using the shared renderer."""
    yield from text_frames(text_columns("HELLO")[1])


def read_line(timeout):
    """Poll Linux/SSH stdin without blocking the scrolling animation."""
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if not ready:
        return None
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    return line.rstrip("\r\n")


def run_matrix(display, columns, interactive=False):
    frames = iter(text_frames(columns))
    redraw = True
    if interactive:
        print("Nhap chu; Enter trong de xoa; go thoat hoac Ctrl+C de dung.")
        print("Nhap noi dung> ", end="", flush=True)
    while True:
        if redraw:
            try:
                frame = next(frames)
            except StopIteration:
                frames = iter(text_frames(columns))
                frame = next(frames)
            display.write_frame(frame)
            redraw = len(columns) > 16
        if interactive:
            try:
                line = read_line(0.1)
            except EOFError:
                return
            if line is not None:
                if line.strip().lower() == "thoat":
                    return
                try:
                    text, replacement = text_columns(line)
                except ValueError as error:
                    print(f"{error}. Giu nguyen noi dung cu.")
                else:
                    columns = replacement
                    frames = iter(text_frames(columns))
                    redraw = True
                    print(f"Hien thi: {text or '(trong)'}")
                print("Nhap noi dung> ", end="", flush=True)
        else:
            time.sleep(0.1 if redraw else 1)


class DisplayLink:
    """Send the display's clock/data protocol, least significant bit first."""

    def __init__(self, gpio, clk, dio, ack=False):
        self.gpio, self.clk, self.dio = gpio, clk, dio
        self.ack = ack
        self.missing_ack = 0

    def delay(self):
        time.sleep(0.00001)

    def start(self):
        self.gpio.output(self.dio, 1)
        self.gpio.output(self.clk, 1)
        self.delay()
        self.gpio.output(self.dio, 0)
        self.delay()
        self.gpio.output(self.clk, 0)

    def stop(self):
        self.gpio.output(self.clk, 0)
        self.gpio.output(self.dio, 0)
        self.delay()
        self.gpio.output(self.clk, 1)
        self.delay()
        self.gpio.output(self.dio, 1)
        self.delay()

    def write_byte(self, value):
        for bit in range(8):
            self.gpio.output(self.clk, 0)
            self.gpio.output(self.dio, (value >> bit) & 1)
            self.delay()
            self.gpio.output(self.clk, 1)
            self.delay()
        self.gpio.output(self.clk, 0)
        # TM1637 has a ninth ACK clock; TM1640 does not.
        if self.ack:
            self.gpio.setup(self.dio, self.gpio.IN, pull_up_down=self.gpio.PUD_UP)
            try:
                self.delay()
                self.gpio.output(self.clk, 1)
                self.delay()
                if self.gpio.input(self.dio):
                    self.missing_ack += 1
            finally:
                self.gpio.output(self.clk, 0)
                self.gpio.setup(self.dio, self.gpio.OUT, initial=self.gpio.LOW)
            self.delay()

    def send(self, values):
        self.start()
        try:
            for value in values:
                self.write_byte(value)
        finally:
            self.stop()

    def show(self, frame, brightness):
        self.send([0x80])  # Disable while loading a known frame.
        self.write_frame(frame)
        self.send([0x88 | brightness])  # Display on, brightness 0..7.

    def write_frame(self, frame):
        """Update RAM while keeping the display enabled between frames."""
        self.send([0x40])  # Write data, increment address automatically.
        self.send([0xC0, *frame])


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bat thu LED 7 doan va ma tran, khong chay motor.")
    parser.add_argument("--target", choices=("7seg", "matrix", "both"), default="both")
    parser.add_argument("--seg-clk", type=int, default=16, help="GPIO BCM CLK cua LED 7 doan")
    parser.add_argument("--seg-dio", type=int, default=6, help="GPIO BCM DIO cua LED 7 doan")
    parser.add_argument("--matrix-clk", type=int, default=7, help="GPIO BCM SCLK cua ma tran")
    parser.add_argument("--matrix-dio", type=int, default=5, help="GPIO BCM DIN cua ma tran")
    parser.add_argument("--number", type=int, default=1234, help="So hien thi 0..9999")
    parser.add_argument("--brightness", type=int, choices=range(8), default=2)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--hello", action="store_true", help="Chay chu HELLO tren ma tran 16x8")
    mode.add_argument("--text", help="Noi dung hien thi tren ma tran (tieng Viet se bo dau)")
    mode.add_argument("--interactive", action="store_true", help="Nhap noi dung lien tuc tu terminal Linux/SSH")
    args = parser.parse_args(argv)
    if not 0 <= args.number <= 9999:
        parser.error("So hien thi phai trong khoang 0..9999.")
    matrix_mode = args.hello or args.interactive or args.text is not None
    if matrix_mode and args.target == "7seg":
        parser.error("Che do chu can --target matrix hoac both.")
    initial_text, columns = "", []
    if args.hello or args.text is not None:
        try:
            initial_text, columns = text_columns("HELLO" if args.hello else args.text)
        except ValueError as error:
            parser.error(str(error))

    selected = []
    if args.target in ("7seg", "both"):
        selected.append(("7seg", args.seg_clk, args.seg_dio, True))
    if args.target in ("matrix", "both"):
        selected.append(("matrix", args.matrix_clk, args.matrix_dio, False))
    pins = [pin for _, clk, dio, _ in selected for pin in (clk, dio)]
    if len(pins) != len(set(pins)) or any(not 2 <= pin <= 27 for pin in pins):
        parser.error("Cac chan GPIO BCM phai khac nhau va nam trong khoang 2..27.")

    try:
        import RPi.GPIO as GPIO
    except (ImportError, RuntimeError) as error:
        print(f"Can Raspberry Pi va thu vien RPi.GPIO: {error}", file=sys.stderr)
        return 1

    configured, displays = [], []
    matrix_display = None
    result = 0
    try:
        GPIO.setmode(GPIO.BCM)
        for name, clk, dio, ack in selected:
            for pin in (clk, dio):
                GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)
                configured.append(pin)
            display = DisplayLink(GPIO, clk, dio, ack=ack)
            displays.append(display)
            if ack:
                frame = [DIGITS[int(digit)] for digit in f"{args.number:04d}"]
            else:
                matrix_display = display
                frame = [0] * 16 if matrix_mode else MATRIX_OK
            display.show(frame, args.brightness)
            expected = f"{args.number:04d}" if ack else (
                (initial_text or "(nhap tai terminal)") if matrix_mode else "OK (co the xoay/nguoc tuy cach lap)"
            )
            print(f"{name}: CLK=BCM{clk}, DATA=BCM{dio}; da gui hinh {expected}.", flush=True)
            if display.missing_ack:
                print("CANH BAO: TM1637 khong ACK day du; kiem tra nguon, chan CLK/DIO va day.", flush=True)
        print("Quan sat LED thuc te de xac nhan. Nhan Ctrl+C de tat va thoat.", flush=True)
        if matrix_mode:
            run_matrix(matrix_display, columns, interactive=args.interactive)
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print("\nDang tat LED...")
    except (OSError, RuntimeError) as error:
        print(f"Loi LED/GPIO: {error}", file=sys.stderr)
        result = 1
    finally:
        try:
            for display in displays:
                try:
                    display.send([0x80])
                except Exception as error:
                    print(f"Khong gui duoc lenh tat LED: {error}", file=sys.stderr)
                    result = 1
        finally:
            if configured:
                GPIO.cleanup(configured)
    return result


if __name__ == "__main__":
    raise SystemExit(main())

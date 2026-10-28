#!/usr/bin/env python3
"""Standalone LED test. Run inside vehicle_testing: python3 test_displays.py.
Scroll HELLO: python3 test_displays.py --target matrix --hello

Defaults are from pi4-source test scripts, not a verified wiring diagram:
TM1637 CLK=BCM16, DIO=BCM6; TM1640 SCLK=BCM7, DIN=BCM5.
Confirm the module power supply and connector pinout before changing wiring.
GPIO7 also belongs to SPI0; it must be free. Run this test on its own.
"""

import argparse
import sys
import time


DIGITS = (0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F)
MATRIX_OK = (0, 0, 0x3E, 0x41, 0x41, 0x41, 0x3E, 0, 0,
             0x7F, 0x08, 0x14, 0x22, 0x41, 0, 0)


def hello_frames():
    """Slide 5x7 HELLO columns right-to-left across a 16-column display.

    Bit 0 is the top row; the eighth row stays blank. Physical orientation
    depends on how the matrix is mounted.
    """
    font = {
        "H": (0x7F, 0x08, 0x08, 0x08, 0x7F),
        "E": (0x7F, 0x49, 0x49, 0x49, 0x41),
        "L": (0x7F, 0x40, 0x40, 0x40, 0x40),
        "O": (0x3E, 0x41, 0x41, 0x41, 0x3E),
    }
    columns = []
    for index, letter in enumerate("HELLO"):
        if index:
            columns.append(0)
        columns.extend(font[letter])
    strip = [0] * 16 + columns + [0] * 16
    for offset in range(len(strip) - 16 + 1):
        yield strip[offset:offset + 16]


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
        self.send([0x40])  # Write data, increment address automatically.
        self.send([0xC0, *frame])
        self.send([0x88 | brightness])  # Display on, brightness 0..7.


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bat thu LED 7 doan va ma tran, khong chay motor.")
    parser.add_argument("--target", choices=("7seg", "matrix", "both"), default="both")
    parser.add_argument("--seg-clk", type=int, default=16, help="GPIO BCM CLK cua LED 7 doan")
    parser.add_argument("--seg-dio", type=int, default=6, help="GPIO BCM DIO cua LED 7 doan")
    parser.add_argument("--matrix-clk", type=int, default=7, help="GPIO BCM SCLK cua ma tran")
    parser.add_argument("--matrix-dio", type=int, default=5, help="GPIO BCM DIN cua ma tran")
    parser.add_argument("--number", type=int, default=1234, help="So hien thi 0..9999")
    parser.add_argument("--brightness", type=int, choices=range(8), default=2)
    parser.add_argument("--hello", action="store_true", help="Chay chu HELLO tren ma tran 16x8")
    args = parser.parse_args(argv)
    if not 0 <= args.number <= 9999:
        parser.error("So hien thi phai trong khoang 0..9999.")
    if args.hello and args.target == "7seg":
        parser.error("--hello can --target matrix hoac both.")

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
                frame = [0] * 16 if args.hello else MATRIX_OK
            display.show(frame, args.brightness)
            expected = f"{args.number:04d}" if ack else (
                "HELLO (chay chu)" if args.hello else "OK (co the xoay/nguoc tuy cach lap)"
            )
            print(f"{name}: CLK=BCM{clk}, DATA=BCM{dio}; da gui hinh {expected}.", flush=True)
            if display.missing_ack:
                print("CANH BAO: TM1637 khong ACK day du; kiem tra nguon, chan CLK/DIO va day.", flush=True)
        print("Quan sat LED thuc te de xac nhan. Nhan Ctrl+C de tat va thoat.", flush=True)
        while True:
            if args.hello:
                for frame in hello_frames():
                    # Keep the display enabled between scrolling frames.
                    matrix_display.send([0x40])
                    matrix_display.send([0xC0, *frame])
                    time.sleep(0.1)
            else:
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

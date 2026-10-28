"""Seven-segment formatting, GPIO ownership and manual/auto session tests."""

import importlib
import io
import subprocess
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


class RecordingLink:
    def __init__(self, *args, **kwargs):
        self.frames = []
        self.commands = []
        self.missing_ack = 0

    def show(self, frame, brightness):
        self.frames.append(list(frame))

    def write_frame(self, frame):
        self.frames.append(list(frame))

    def send(self, values):
        self.commands.append(list(values))


class GPIO:
    BCM, OUT, HIGH = 11, 0, 1

    def __init__(self):
        self.pins = {12, 18}
        self.cleaned = []
        self.fail_pin = None

    def setmode(self, mode):
        if mode != self.BCM:
            raise ValueError("BCM required")

    def setup(self, pin, mode, **kwargs):
        if pin == self.fail_pin:
            raise OSError("setup failed")
        self.pins.add(pin)

    def cleanup(self, pins):
        self.cleaned.append(list(pins))
        self.pins.difference_update(pins)


class Sensor:
    def __init__(self, readings):
        self.readings = iter(readings)
        self.closed = False
        self.calls = 0

    def read_distance_cm(self):
        self.calls += 1
        value = next(self.readings)
        if isinstance(value, Exception):
            raise value
        return value

    def close(self):
        self.closed = True


class EntryTests(unittest.TestCase):
    def test_module_import_does_not_open_gpio_or_motor_hardware(self):
        result = subprocess.run(
            [sys.executable, "-B", "-c", "import sys; from vehicle_testing.seven_segment import SevenSegmentDisplay; "
             "assert not any(n in sys.modules for n in ('RPi.GPIO', 'board', 'vehicle_testing.controller', 'vehicle_testing.hand'))"],
            cwd=ROOT, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_direct_and_module_help_do_not_require_gpio(self):
        for argv, cwd in ((["seven_segment.py", "--help"], ROOT / "vehicle_testing"),
                          (["-m", "vehicle_testing.seven_segment", "--help"], ROOT)):
            with self.subTest(argv=argv):
                result = subprocess.run([sys.executable, "-B", *argv], cwd=cwd, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--auto", result.stdout)


class TransportTests(unittest.TestCase):
    def test_byte_is_lsb_first_and_only_tm1637_has_an_ack_clock(self):
        from vehicle_testing.display_link import DisplayLink

        class PinIO:
            IN, OUT, LOW, PUD_UP = 1, 0, 0, 22

            def __init__(self):
                self.data = 0
                self.edges = []
                self.mode = self.OUT

            def output(self, pin, level):
                if pin == 6:
                    self.data = level
                elif level:
                    self.edges.append(self.data)

            def setup(self, pin, mode, **kwargs):
                self.mode = mode
                self.data = kwargs.get("initial", 0)

            def input(self, pin):
                return 0

        for ack in (False, True):
            gpio = PinIO()
            link = DisplayLink(gpio, 16, 6, ack=ack)
            with patch.object(link, "delay"):
                link.write_byte(0xA5)
            self.assertEqual(gpio.edges[:8], [1, 0, 1, 0, 0, 1, 0, 1])
            self.assertEqual(len(gpio.edges), 9 if ack else 8)
            self.assertEqual(gpio.mode, gpio.OUT)


class DisplayFixture(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("vehicle_testing.seven_segment")
        self.gpio = GPIO()
        self.link = RecordingLink()
        self.patcher = patch.object(self.module, "DisplayLink", return_value=self.link)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def display(self, **kwargs):
        return self.module.SevenSegmentDisplay(gpio=self.gpio, **kwargs)


class DisplayTests(DisplayFixture):
    def test_numbers_pad_to_four_digits_and_round_half_up(self):
        with self.display() as display:
            display.show_number(123)
            self.assertEqual(self.link.frames[-1], [0x3F, 0x06, 0x5B, 0x4F])
            display.show_number(27.5)
            self.assertEqual(self.link.frames[-1], [0x3F, 0x3F, 0x5B, 0x7F])

    def test_invalid_number_preserves_the_previous_frame(self):
        with self.display() as display:
            display.show_number(123)
            previous = list(self.link.frames)
            for value in (-1, 10000, float("nan"), float("inf"), True, "123"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    display.show_number(value)
            self.assertEqual(self.link.frames, previous)

    def test_error_clear_and_brightness_change_have_separate_effects(self):
        with self.display() as display:
            display.show_error()
            self.assertEqual(self.link.frames[-1], [0x40] * 4)
            before = list(self.link.frames)
            display.set_brightness(7)
            self.assertEqual(self.link.frames, before)
            self.assertEqual(self.link.commands[-1], [0x8F])
            display.clear()
            self.assertEqual(self.link.frames[-1], [0] * 4)

    def test_close_disables_led_and_only_releases_owned_gpio_once(self):
        display = self.display()
        display.close()
        display.close()
        self.assertEqual(self.link.commands[-1], [0x80])
        self.assertEqual(self.gpio.cleaned, [[16, 6]])
        self.assertEqual(self.gpio.pins, {12, 18})
        with self.assertRaises(RuntimeError):
            display.show_number(1)

    def test_failed_led_shutdown_still_releases_gpio(self):
        display = self.display()
        with patch.object(self.link, "send", side_effect=OSError("write failed")):
            with self.assertRaises(OSError):
                display.close()
        self.assertEqual(self.gpio.pins, {12, 18})

    def test_partial_setup_and_invalid_config_do_not_touch_other_gpio(self):
        for kwargs in ({"clk": 6}, {"dio": True}, {"brightness": 8}):
            with self.assertRaises(ValueError):
                self.display(**kwargs)
        self.gpio.fail_pin = 6
        with self.assertRaises(OSError):
            self.display()
        self.assertEqual(self.gpio.cleaned, [[16]])
        self.assertEqual(self.gpio.pins, {12, 18})

    def test_main_rejects_sensor_pin_overlap_before_opening_sensor(self):
        with patch.dict(sys.modules, {"RPi": SimpleNamespace(GPIO=self.gpio), "RPi.GPIO": self.gpio}), \
                patch.object(self.module, "read_line", return_value="thoat"), \
                patch.object(self.module, "UltrasonicSensor") as sensor_factory, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(self.module.main(["--auto", "--trig", "16"]), 0)
        sensor_factory.assert_not_called()
        self.assertIn([0x40] * 4, self.link.frames)
        self.assertEqual(self.gpio.pins, {12, 18})

    def test_sensor_cleanup_failure_still_disables_led_and_cleans_its_pins(self):
        sensor = Sensor([12])
        with patch.dict(sys.modules, {"RPi": SimpleNamespace(GPIO=self.gpio), "RPi.GPIO": self.gpio}), \
                patch.object(self.module, "read_line", side_effect=EOFError), \
                patch.object(self.module, "UltrasonicSensor", return_value=sensor), \
                patch.object(sensor, "close", side_effect=OSError("sensor cleanup failed")), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(self.module.main(["--auto"]), 1)
        self.assertEqual(self.link.commands[-1], [0x80])
        self.assertEqual(self.gpio.pins, {12, 18})


class SessionTests(DisplayFixture):
    def run_session(self, display, inputs, sensor_factory=None, **kwargs):
        # Advance a virtual clock by each requested input wait, not wall time.
        now = [0.0]
        lines = iter(inputs)

        def reader(timeout):
            now[0] += timeout
            item = next(lines)
            if isinstance(item, BaseException):
                raise item
            return item

        with redirect_stdout(io.StringIO()):
            self.module.run_session(display, reader=reader, sensor_factory=sensor_factory,
                                    monotonic=lambda: now[0], **kwargs)

    def test_manual_mode_does_not_open_sensor_and_empty_line_clears(self):
        with self.display() as display, patch.object(self.module, "UltrasonicSensor") as factory:
            self.run_session(display, ["123", "bad", "", "thoat"])
            factory.assert_not_called()
        self.assertIn([0x3F, 0x06, 0x5B, 0x4F], self.link.frames)
        self.assertEqual(self.link.frames[-1], [0] * 4)

    def test_auto_timeout_invalid_sample_and_recovery_then_manual_close_sensor(self):
        sensor = Sensor([TimeoutError("no echo"), float("nan"), 27.5])
        with self.display() as display:
            self.run_session(display, ["auto", None, None, None, None, None, "123", "thoat"],
                             sensor_factory=lambda: sensor)
        self.assertEqual(sensor.calls, 3)
        self.assertTrue(sensor.closed)
        self.assertIn([0x40] * 4, self.link.frames)
        self.assertIn([0x3F, 0x3F, 0x5B, 0x7F], self.link.frames)
        self.assertEqual(self.link.frames[-1], [0x3F, 0x06, 0x5B, 0x4F])

    def test_leaving_auto_releases_sensor_before_next_manual_input(self):
        sensor = Sensor([12])
        calls = iter(["auto", "123", "thoat"])

        def reader(timeout):
            item = next(calls)
            if item == "thoat":
                self.assertTrue(sensor.closed)
            return item

        with self.display() as display, redirect_stdout(io.StringIO()):
            self.module.run_session(display, reader=reader, sensor_factory=lambda: sensor)

    def test_bad_auto_input_does_not_disable_future_measurements(self):
        sensor = Sensor([12, 13])
        with self.display() as display:
            self.run_session(display, ["auto", "not a number", None, None, "thoat"],
                             sensor_factory=lambda: sensor)
        self.assertEqual(sensor.calls, 2)

    def test_sensor_init_failure_still_allows_manual_input(self):
        def fail():
            raise OSError("sensor missing")
        with self.display() as display:
            self.run_session(display, ["auto", "123", "thoat"], sensor_factory=fail)
        self.assertIn([0x40] * 4, self.link.frames)
        self.assertEqual(self.link.frames[-1], [0x3F, 0x06, 0x5B, 0x4F])

    def test_eof_or_interrupt_releases_active_sensor(self):
        for error in (EOFError(), KeyboardInterrupt()):
            sensor = Sensor([12])
            with self.subTest(error=type(error).__name__), self.display() as display:
                if isinstance(error, KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt):
                        self.run_session(display, ["auto", error], sensor_factory=lambda: sensor)
                else:
                    self.run_session(display, ["auto", error], sensor_factory=lambda: sensor)
            self.assertTrue(sensor.closed)


if __name__ == "__main__":
    unittest.main()

"""Exercise sensor timing and GPIO ownership without Raspberry Pi hardware."""

import importlib
import io
from pathlib import Path
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        self.now += 0.000001
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class SensorGPIO:
    BCM, IN, OUT, LOW, HIGH = 11, 1, 0, 0, 1

    def __init__(self, clock):
        self.clock = clock
        self.pins = {12: "claw", 18: "lift"}
        self.writes = []
        self.cleanups = []
        self.pulse = None
        self.echo_seconds = 0.002
        self.missing_echo = False
        self.stuck_high = False
        self.never_falls = False
        self.fail_setup = None

    def setmode(self, mode):
        if mode != self.BCM:
            raise ValueError("BCM required")

    def setup(self, pin, direction, **kwargs):
        if pin == self.fail_setup:
            raise OSError("setup failed")
        self.pins[pin] = direction

    def output(self, pin, level):
        if self.pins.get(pin) != self.OUT:
            raise ValueError("Output pin was not configured")
        self.writes.append((pin, level))
        if level == self.LOW and len(self.writes) >= 2 and self.writes[-2][1] == self.HIGH:
            self.pulse = self.clock.now + 0.0001

    def input(self, pin):
        if self.pins.get(pin) != self.IN:
            raise ValueError("Input pin was not configured")
        if self.stuck_high:
            return 1
        if self.missing_echo or self.pulse is None:
            return 0
        if self.clock.now < self.pulse:
            return 0
        return int(self.never_falls or self.clock.now < self.pulse + self.echo_seconds)

    def cleanup(self, pins):
        self.cleanups.append(list(pins))
        for pin in pins:
            self.pins.pop(pin, None)


class ImportTests(unittest.TestCase):
    def test_cli_runs_directly_inside_vehicle_folder_and_as_package(self):
        for arguments, cwd in (
            (["ultrasonic.py", "--help"], ROOT / "vehicle_testing"),
            (["-m", "vehicle_testing.hardware.ultrasonic", "--help"], ROOT),
        ):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, "-B", *arguments], cwd=cwd,
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--trig", result.stdout)
                self.assertIn("--echo", result.stdout)

    def test_import_does_not_open_gpio_motor_or_servo_modules(self):
        result = subprocess.run(
            [sys.executable, "-B", "-c",
             "import sys; from vehicle_testing.hardware.ultrasonic import UltrasonicSensor; "
             "assert not any(name in sys.modules for name in "
             "('RPi.GPIO', 'board', 'vehicle_testing.hardware.motors', 'vehicle_testing.hardware.servos'))"],
            cwd=ROOT, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class UltrasonicTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("vehicle_testing.hardware.ultrasonic")
        self.clock = FakeClock()
        self.gpio = SensorGPIO(self.clock)

    def sensor(self, **kwargs):
        return self.module.UltrasonicSensor(
            gpio=self.gpio, monotonic=self.clock.monotonic,
            sleeper=self.clock.sleep, **kwargs,
        )

    def test_two_millisecond_echo_is_34_point_3_cm_and_trigger_returns_low(self):
        with self.sensor() as sensor:
            distance = sensor.read_distance_cm()
        self.assertAlmostEqual(distance, 34.3, delta=0.03)
        self.assertEqual(self.gpio.writes, [(8, 0), (8, 1), (8, 0)])
        self.assertEqual(self.gpio.pins, {12: "claw", 18: "lift"})

    def test_custom_pins_are_used_and_only_owned_pins_are_released(self):
        with self.sensor(trig=17, echo=27) as sensor:
            self.assertGreater(sensor.read_distance_cm(), 0)
        self.assertEqual(self.gpio.writes[1], (17, 1))
        self.assertEqual(self.gpio.cleanups, [[17, 27]])
        self.assertEqual(self.gpio.pins, {12: "claw", 18: "lift"})

    def test_missing_rise_and_missing_fall_each_have_a_bounded_timeout(self):
        for failure in ("missing_echo", "never_falls"):
            with self.subTest(failure=failure):
                with self.sensor() as sensor:
                    setattr(self.gpio, failure, True)
                    before = self.clock.now
                    with self.assertRaises(TimeoutError):
                        sensor.read_distance_cm()
                    self.assertLess(self.clock.now - before, 0.04)
                    setattr(self.gpio, failure, False)

    def test_echo_high_before_trigger_is_reported_without_triggering(self):
        with self.sensor() as sensor:
            self.gpio.stuck_high = True
            with self.assertRaisesRegex(TimeoutError, "HIGH"):
                sensor.read_distance_cm()
        self.assertEqual(self.gpio.writes, [])

    def test_next_read_can_recover_after_a_timeout(self):
        with self.sensor() as sensor:
            self.gpio.missing_echo = True
            with self.assertRaises(TimeoutError):
                sensor.read_distance_cm()
            self.gpio.missing_echo = False
            self.assertAlmostEqual(sensor.read_distance_cm(), 34.3, delta=0.03)

    def test_short_echo_is_returned_instead_of_being_replaced_with_clear_path(self):
        self.gpio.echo_seconds = 0.0001
        with self.sensor() as sensor:
            self.assertAlmostEqual(sensor.read_distance_cm(), 1.715, delta=0.03)

    def test_invalid_configuration_does_not_claim_any_gpio(self):
        for kwargs in ({"trig": 11}, {"echo": True}, {"trig": 28},
                       {"timeout": 0}, {"timeout": float("nan")}, {"timeout": float("inf")}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.sensor(**kwargs)
                self.assertEqual(self.gpio.pins, {12: "claw", 18: "lift"})

    def test_partial_setup_failure_releases_only_successfully_configured_pin(self):
        self.gpio.fail_setup = 11
        with self.assertRaisesRegex(OSError, "setup failed"):
            self.sensor()
        self.assertEqual(self.gpio.cleanups, [[8]])
        self.assertEqual(self.gpio.pins, {12: "claw", 18: "lift"})

    def test_close_is_idempotent_and_closed_sensor_cannot_read(self):
        sensor = self.sensor()
        sensor.close()
        sensor.close()
        with self.assertRaises(RuntimeError):
            sensor.read_distance_cm()
        self.assertEqual(self.gpio.cleanups, [[8, 11]])

    def test_interrupt_during_trigger_lowers_trigger_and_context_releases_gpio(self):
        original_sleep = self.clock.sleep

        def interrupt_trigger(seconds):
            if seconds == 0.00001:
                raise KeyboardInterrupt
            original_sleep(seconds)

        with patch.object(self.clock, "sleep", side_effect=interrupt_trigger):
            with self.assertRaises(KeyboardInterrupt), self.sensor() as sensor:
                sensor.read_distance_cm()
        self.assertEqual(self.gpio.writes[-1], (8, 0))
        self.assertEqual(self.gpio.pins, {12: "claw", 18: "lift"})

    def test_cli_reports_reading_and_timeout_then_closes_on_ctrl_c(self):
        sensor = self.sensor()
        output = io.StringIO()
        with patch.object(self.module, "UltrasonicSensor", return_value=sensor), \
                patch.object(sensor, "read_distance_cm", side_effect=[34.3, TimeoutError("no echo"), KeyboardInterrupt]), \
                patch.object(self.module.time, "sleep"), redirect_stdout(output):
            self.assertEqual(self.module.main([]), 0)
        self.assertIn("34.3 cm", output.getvalue())
        self.assertIn("KHONG DOC DUOC", output.getvalue())
        self.assertEqual(self.gpio.pins, {12: "claw", 18: "lift"})


if __name__ == "__main__":
    unittest.main()

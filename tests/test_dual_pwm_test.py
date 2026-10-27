"""Separate dual hardware PWM trial: use fixtures/mocks, never robot hardware."""

import importlib
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import Mock, patch


class DualPWMTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("vehicle_testing.dual_pwm_test")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.chips = {}
        self.factory = Mock(side_effect=self.make_pwm)
        self.pin_reader = Mock(side_effect=lambda pin: f"{pin}: a0 pd | lo // GPIO{pin} = PWM0_{pin - 12}")
        capture = redirect_stdout(io.StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def make_pwm(self, *, pwm_channel, hz, chip):
        self.chips[pwm_channel] = Mock()
        return self.chips[pwm_channel]

    def chip(self, index, compatible=b"brcm,bcm2835-pwm\0", channels=2, address=0x7e20c000):
        path = self.root / f"pwmchip{index}"
        node = path / "device/of_node"
        node.mkdir(parents=True)
        (node / "compatible").write_bytes(compatible)
        (node / "reg").write_bytes(address.to_bytes(4, "big") + b"\0\0\0\x28")
        (path / "npwm").write_text(str(channels), encoding="ascii")

    def main(self, commands, args=(), sleeper=lambda _: None):
        log = io.StringIO()
        with redirect_stdout(log), redirect_stderr(log):
            result = self.module.main(list(args), sysfs_root=self.root, pin_reader=self.pin_reader,
                                      pwm_factory=self.factory, input_fn=Mock(side_effect=commands),
                                      sleeper=sleeper)
        return result, log.getvalue()

    def test_discovers_pi4_hardware_block_and_rejects_gpio_or_audio_block(self):
        self.chip(0, compatible=b"pwm-gpio\0", channels=1)
        self.chip(1, address=0x7e20c800)
        self.chip(3)
        self.assertEqual(self.module.find_pwm_chip(None, self.root), 3)
        with self.assertRaises(RuntimeError):
            self.module.find_pwm_chip(0, self.root)

    def test_missing_or_ambiguous_provider_is_not_guessed(self):
        with self.assertRaises(RuntimeError):
            self.module.find_pwm_chip(None, self.root)
        self.chip(0)
        self.chip(2)
        with self.assertRaises(RuntimeError):
            self.module.find_pwm_chip(None, self.root)
        self.assertEqual(self.module.find_pwm_chip(2, self.root), 2)

    def test_check_mode_reads_pins_without_creating_pwm(self):
        self.chip(1)
        status, log = self.main([], ["--check"])
        self.assertEqual(status, 0)
        self.assertIn("pwmchip1", log)
        self.assertEqual(self.pin_reader.call_count, 2)
        self.factory.assert_not_called()

    def test_wrong_pin_mode_fails_before_output_creation(self):
        self.chip(0)
        self.pin_reader.side_effect = lambda pin: f"{pin}: ip pd | lo" if pin == 13 else "12: a0 pd | lo"
        status, log = self.main(["nang 4", "thoat"])
        self.assertEqual(status, 1)
        self.assertIn("BCM 13", log)
        self.factory.assert_not_called()

    def test_startup_and_invalid_input_do_not_emit_position_pulses(self):
        self.chip(0)
        status, _ = self.main(["", "chay", "nang nan", "ha 0.1", "thoat"])
        self.assertEqual(status, 0)
        self.factory.assert_not_called()

    def test_sweep_lasts_requested_time_without_restarting_pwm_and_is_exact_at_end(self):
        elapsed, writes = [0.0], []
        output = Mock()
        output.start.side_effect = lambda duty: writes.append((elapsed[0], duty))
        output.change_duty_cycle.side_effect = lambda duty: writes.append((elapsed[0], duty))
        controller = self.module.ServoTrial(3, pwm_factory=Mock(return_value=output),
                                            sleeper=lambda sec: elapsed.__setitem__(0, elapsed[0] + sec))
        with patch.object(self.module.time, "monotonic", side_effect=lambda: elapsed[0]):
            controller.move("nang", 4)
        self.assertEqual(writes[0], (0.0, 3.0))
        self.assertAlmostEqual(writes[-1][0], 4)
        self.assertAlmostEqual(writes[-1][1], 8.5)
        self.assertAlmostEqual(elapsed[0], 4.1)
        self.assertTrue(all(a[1] <= b[1] for a, b in zip(writes, writes[1:])))
        with patch.object(self.module.time, "monotonic", side_effect=lambda: elapsed[0]):
            controller.move("ha", 3)
        output.start.assert_called_once()
        self.assertAlmostEqual(output.change_duty_cycle.call_args.args[0], 3)
        controller.close()
        output.stop.assert_called()

    def test_slow_writes_do_not_accumulate_into_motion_deadline(self):
        elapsed, writes = [0.0], []
        output = Mock()
        def write(duty):
            writes.append((elapsed[0], duty))
            elapsed[0] += 0.01  # Simulated sysfs write cost, not a real GPIO operation.
        output.start.side_effect = write
        output.change_duty_cycle.side_effect = write
        controller = self.module.ServoTrial(0, pwm_factory=Mock(return_value=output),
                                            sleeper=lambda sec: elapsed.__setitem__(0, elapsed[0] + sec))
        with patch.object(self.module.time, "monotonic", side_effect=lambda: elapsed[0]):
            controller.move("nang", 4)
        self.assertAlmostEqual(writes[-1][1], 8.5)
        self.assertLessEqual(writes[-1][0], 4.02)
        self.assertLessEqual(elapsed[0], 4.13)
        controller.close()

    def test_independent_channels_and_cleanup_both_even_if_one_stop_fails(self):
        controller = self.module.ServoTrial(1, pwm_factory=self.factory, sleeper=lambda _: None)
        controller.move("nang", 2)
        controller.move("mo_cang", 2)
        self.factory.assert_any_call(pwm_channel=1, hz=50, chip=1)
        self.factory.assert_any_call(pwm_channel=0, hz=50, chip=1)
        self.chips[0].stop.side_effect = OSError("channel 0 stop failed")
        self.chips[1].stop.reset_mock()
        with self.assertRaises(RuntimeError):
            controller.close()
        self.chips[1].stop.assert_called_once()

    def test_interrupt_during_first_motion_stops_lift(self):
        self.chip(0)
        status, _ = self.main(["nang 4"], sleeper=Mock(side_effect=KeyboardInterrupt()))
        self.assertEqual(status, 130)
        self.chips[1].stop.assert_called()

    def test_failed_initial_stop_is_still_cleaned_up(self):
        self.chip(0)
        output = Mock()
        output.stop.side_effect = [OSError("stop failed"), None]
        self.factory.side_effect = None
        self.factory.return_value = output
        status, log = self.main(["nang 4"])
        self.assertEqual(status, 1)
        self.assertIn("stop failed", log)
        self.assertEqual(output.stop.call_count, 2)
        output.start.assert_not_called()

    def test_dry_run_skips_all_hardware_validation_and_creation(self):
        status, log = self.main(["nang 2", "ha 2", "thoat"], ["--dry-run"])
        self.assertEqual(status, 0)
        self.assertIn("MO PHONG", log)
        self.factory.assert_not_called()
        self.pin_reader.assert_not_called()

    def test_missing_pin_tool_is_reported_without_creating_pwm(self):
        self.chip(0)
        self.pin_reader.side_effect = FileNotFoundError("pinctrl")
        status, log = self.main(["nang 4"])
        self.assertEqual(status, 1)
        self.factory.assert_not_called()

    def test_invalid_pulse_parameters_fail_before_hardware(self):
        for args in (["--down-us", "nan"], ["--up-us", "2501"],
                     ["--down-us", "600", "--up-us", "600"]):
            with self.subTest(args=args), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    self.module.main(args, pwm_factory=self.factory)
        self.factory.assert_not_called()

    def test_standalone_dry_run_without_vehicle_package_or_hardware_libraries(self):
        script = Path(self.module.__file__).resolve()
        copy = self.root / "dual_pwm_test.py"
        copy.write_bytes(script.read_bytes())
        result = subprocess.run([sys.executable, str(copy), "--dry-run"], cwd=self.root,
                                input="nang 2\nha 2\nthoat\n", text=True,
                                capture_output=True, timeout=12)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nang", result.stdout)
        self.assertIn("ha", result.stdout)


if __name__ == "__main__":
    unittest.main()

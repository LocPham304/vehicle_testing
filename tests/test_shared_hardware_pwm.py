"""Tests for sharing BCM2711 hardware PWM0_0 across BCM 18 (ALT5) and BCM 12 (ALT0)."""

import importlib
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class BCM2711PinMuxTests(unittest.TestCase):
    def setUp(self):
        self.pwm_mod = importlib.import_module("vehicle_testing.hardware.pwm")
        self.buf = bytearray(64)

    def _read_word(self, word_index: int) -> int:
        return struct.unpack_from("<I", self.buf, word_index * 4)[0]

    def _write_word(self, word_index: int, value: int) -> None:
        struct.pack_into("<I", self.buf, word_index * 4, value)

    def test_route_lift_and_claw_preserves_other_gpfsel1_pins_and_clears_latches(self):
        # Pre-populate GPIO 11 (bits 5:3 = 0b111) and GPIO 16 (bits 20:18 = 0b001).
        neighbor_bits = (0b111 << 3) | (0b001 << 18) | (0b101 << 27)
        self._write_word(self.pwm_mod.GPFSEL1_WORD, neighbor_bits)
        mux = self.pwm_mod.BCM2711PinMux(self.buf)

        mux.route_pwm0(18)
        self.assertEqual(self._read_word(self.pwm_mod.GPCLR0_WORD), (1 << 12) | (1 << 18))
        gpfsel1 = self._read_word(self.pwm_mod.GPFSEL1_WORD)
        self.assertEqual((gpfsel1 >> 24) & 0b111, 0b010)  # BCM 18 = ALT5 (PWM0_0)
        self.assertEqual((gpfsel1 >> 6) & 0b111, 0b001)   # BCM 12 = Output LOW
        self.assertEqual(gpfsel1 & neighbor_bits, neighbor_bits)

        self._write_word(self.pwm_mod.GPCLR0_WORD, 0)
        mux.route_pwm0(12)
        self.assertEqual(self._read_word(self.pwm_mod.GPCLR0_WORD), (1 << 12) | (1 << 18))
        gpfsel1 = self._read_word(self.pwm_mod.GPFSEL1_WORD)
        self.assertEqual((gpfsel1 >> 6) & 0b111, 0b100)   # BCM 12 = ALT0 (PWM0_0)
        self.assertEqual((gpfsel1 >> 24) & 0b111, 0b001)  # BCM 18 = Output LOW
        self.assertEqual(gpfsel1 & neighbor_bits, neighbor_bits)

        mux.close()
        gpfsel1 = self._read_word(self.pwm_mod.GPFSEL1_WORD)
        self.assertEqual((gpfsel1 >> 6) & 0b111, 0b001)
        self.assertEqual((gpfsel1 >> 24) & 0b111, 0b001)
        self.assertEqual(gpfsel1 & neighbor_bits, neighbor_bits)
        with self.assertRaises(RuntimeError):
            mux.route_pwm0(18)

    def test_unsupported_pin_or_soc_is_rejected(self):
        mux = self.pwm_mod.BCM2711PinMux(self.buf)
        with self.assertRaises(ValueError):
            mux.route_pwm0(17)
        mux.close()

        with tempfile.TemporaryDirectory() as tmp:
            compat = Path(tmp) / "compatible"
            compat.write_bytes(b"raspberrypi,5-model-b\0brcm,bcm2712\0")
            with self.assertRaisesRegex(RuntimeError, "Pi 5"):
                self.pwm_mod.BCM2711PinMux(dt_compatible_paths=(compat,))

            compat.write_bytes(b"raspberrypi,4-model-b\0brcm,bcm2711\0")
            missing_mem = Path(tmp) / "missing_gpiomem"
            with self.assertRaisesRegex(RuntimeError, "gpiomem"):
                self.pwm_mod.BCM2711PinMux(
                    gpiomem_path=missing_mem,
                    dt_compatible_paths=(compat,),
                )


class HardwarePWMChipDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.pwm_mod = importlib.import_module("vehicle_testing.hardware.pwm")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _chip(self, index: int, compatible: bytes) -> None:
        node = self.root / f"pwmchip{index}" / "device" / "of_node"
        node.mkdir(parents=True)
        (node / "compatible").write_bytes(compatible)

    def test_discovers_bcm_hardware_pwm_whether_pwm_gpio_is_present_or_removed(self):
        # Case 1: pwmchip0 = pwm-gpio, pwmchip1 = brcm,bcm2835-pwm
        self._chip(0, b"pwm-gpio\0")
        self._chip(1, b"brcm,bcm2835-pwm\0")
        self.assertEqual(self.pwm_mod.find_hardware_pwm_chip(1, self.root), 1)
        self.assertEqual(self.pwm_mod.find_hardware_pwm_chip(0, self.root), 1)

    def test_discovers_renumbered_pwmchip0_when_pwm_gpio_overlay_is_removed(self):
        self._chip(0, b"brcm,bcm2835-pwm\0")
        self.assertEqual(self.pwm_mod.find_hardware_pwm_chip(1, self.root), 0)

    def test_missing_hardware_pwm_chip_raises_setup_error(self):
        self._chip(0, b"pwm-gpio\0")
        with self.assertRaisesRegex(RuntimeError, "dtoverlay=pwm,pin=12,func=4"):
            self.pwm_mod.find_hardware_pwm_chip(1, self.root)


class SharedHardwarePWM0Tests(unittest.TestCase):
    def setUp(self):
        self.servos = importlib.import_module("vehicle_testing.hardware.servos")
        self.pwm_mod = importlib.import_module("vehicle_testing.hardware.pwm")
        self.buf = bytearray(64)
        self.events: list[tuple] = []

        class RecordingMux(self.pwm_mod.BCM2711PinMux):
            def __init__(mux_self):
                super().__init__(self.buf)

            def route_pwm0(mux_self, active_pin: int) -> None:
                self.events.append(("route", active_pin))
                super().route_pwm0(active_pin)

            def isolate_all(mux_self) -> None:
                self.events.append(("isolate",))
                super().isolate_all()

        self.mux_cls = RecordingMux
        self.hardware = Mock()
        self.hw_pwm = self.hardware.HardwarePWM.return_value
        self.hw_pwm.start.side_effect = lambda d: self.events.append(("start", round(d, 4)))
        self.hw_pwm.change_duty_cycle.side_effect = lambda d: self.events.append(("duty", round(d, 4)))
        self.hw_pwm.stop.side_effect = lambda: self.events.append(("stop",))

    def test_lazy_creation_and_glitch_free_handover_between_lift_and_claw(self):
        with patch.dict("sys.modules", {"rpi_hardware_pwm": self.hardware}), \
                patch.object(self.servos, "find_hardware_pwm_chip", return_value=1), \
                patch.object(self.servos, "SERVO_CALIBRATED", True):
            bus = self.servos.SharedHardwarePWM0(mux_factory=self.mux_cls)
            self.assertEqual(self.events, [])  # Lazy until first servo output opens.

            lift = bus.lift_output()
            claw = bus.claw_output()
            self.hardware.HardwarePWM.assert_called_once_with(pwm_channel=0, hz=50, chip=1)
            self.events.clear()

            # Lift move (-10 -> 80 deg => 450 us -> 1400 us, i.e. 2.25% -> 7.0%)
            lift.set_angle(-10)
            lift.set_angle(-10)  # Duplicate rounded pulse suppressed.
            lift.set_angle(80)
            # Even WITHOUT calling lift.release() (simulating SERVO_HOLD_POSITION=True),
            # switching to claw MUST stop PWM0 BEFORE routing to BCM 12!
            claw.set_angle(100)
            claw.set_angle(0)
            claw.release()

            self.assertEqual(
                self.events,
                [
                    ("route", 18),
                    ("start", 2.25),
                    ("duty", 7.0),
                    ("stop",),       # Stops lift pulse BEFORE switching pin mux to claw!
                    ("route", 12),
                    ("start", 8.055),
                    ("duty", 2.5),
                    ("stop",),
                    ("isolate",),
                ],
            )
            bus.close()

    def test_release_isolates_pins_even_if_pwm_stop_raises(self):
        with patch.dict("sys.modules", {"rpi_hardware_pwm": self.hardware}), \
                patch.object(self.servos, "find_hardware_pwm_chip", return_value=1), \
                patch.object(self.servos, "SERVO_CALIBRATED", True):
            bus = self.servos.SharedHardwarePWM0(mux_factory=self.mux_cls)
            lift = bus.lift_output()
            lift.set_angle(-10)
            self.hw_pwm.stop.side_effect = OSError("sysfs stop error")
            with self.assertRaises(OSError):
                lift.release()
            gpfsel1 = struct.unpack_from("<I", self.buf, 4)[0]
            self.assertEqual((gpfsel1 >> 18 * 0 + 6) & 0b111, 0b001)
            self.assertEqual((gpfsel1 >> 24) & 0b111, 0b001)


if __name__ == "__main__":
    unittest.main()

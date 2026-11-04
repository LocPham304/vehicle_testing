"""Experimental SDK for converted FE programs. Dry-run unless the worker opts in."""

import json
import logging
import math
from pathlib import Path
import time


logger = logging.getLogger(__name__)
_options = {'dry_run': True, 'stop_file': None, 'speed': 0.25, 'lift_start_lowered': False}
_robots = []


class RobotStopped(Exception):
    """Cooperative cancellation, handled by the Python worker."""


def configure(*, dry_run=True, stop_file=None, speed=0.25, lift_start_lowered=False):
    if not math.isfinite(speed) or not 0 < speed <= 1:
        raise ValueError('PWM speed phải trong (0, 1].')
    _options.update(dry_run=dry_run, stop_file=Path(stop_file) if stop_file else None,
                    speed=speed, lift_start_lowered=lift_start_lowered)


def _open_motor(dry_run, sleeper):
    from vehicle_testing.hardware.motors import DryRunOutput, MotorController
    from vehicle_testing.runtime.runner import open_motor
    return MotorController(DryRunOutput(), sleeper=sleeper) if dry_run else open_motor(sleeper=sleeper)


def _open_hand(dry_run, sleeper):
    from vehicle_testing.hardware.servos import DryRunServoOutput, HandController, KernelPWMLiftOutput
    return HandController(DryRunServoOutput if dry_run else KernelPWMLiftOutput,
                          sleeper=sleeper, calibration_required=not dry_run)


def _open_matrix(dry_run, sleeper):
    from vehicle_testing.runtime.runner import DryRunMatrix, MatrixTextDisplay
    return DryRunMatrix() if dry_run else MatrixTextDisplay(sleeper=sleeper)


class Robot:
    def __init__(self):
        self.dry_run = _options['dry_run']
        self.stop_file = _options['stop_file']
        self.speed = _options['speed']
        self.lift_start_lowered = _options['lift_start_lowered']
        self._motor = self._hand = self._matrix = None
        self._closed = False
        self._cleanup_errors = []
        _robots.append(self)
        logger.info('SDK MODE: %s; tiến/lùi tính bằng giây; PWM=%g%%',
                    'MO PHONG' if self.dry_run else 'PHAN CUNG THAT', self.speed * 100)

    def _check(self):
        if self._closed:
            raise RobotStopped('Robot đã dừng, không nhận thêm hành động trong lượt chạy này.')
        if self.stop_file is not None and self.stop_file.exists():
            raise RobotStopped('Đã nhận yêu cầu Stop.')

    def _sleep(self, seconds):
        self._check()
        if self.dry_run:
            return
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self._check()
            time.sleep(min(0.02, max(0, deadline - time.monotonic())))
        self._check()

    def _get_motor(self):
        self._check()
        if self._motor is None:
            self._motor = _open_motor(self.dry_run, self._sleep)
            self._motor.stop()
        return self._motor

    def report_block(self, block_id):
        self._check()
        print(json.dumps({'event': 'block', 'block_id': block_id}, ensure_ascii=False), flush=True)

    def move_forward(self, seconds):
        self._get_motor().move('forward', seconds, speed=self.speed)

    def move_backward(self, seconds):
        self._get_motor().move('backward', seconds, speed=self.speed)

    def turn_left(self, degrees):
        self._get_motor().turn_left(degrees)

    def turn_right(self, degrees):
        self._get_motor().turn_right(degrees)

    def hand_up(self, degrees):
        self._check()
        if not self.dry_run and not self.lift_start_lowered:
            raise ValueError('Cần xác nhận tay bắt đầu ở vị trí hạ trước lượt nâng thật.')
        if self._motor is not None:
            self._motor.stop()
        if self._hand is None:
            self._hand = _open_hand(self.dry_run, self._sleep)
        self._hand.hand_up(angle=degrees)

    def led_strip(self, text):
        self._check()
        if self._matrix is None:
            self._matrix = _open_matrix(self.dry_run, self._sleep)
        self._matrix.show_text(text)

    def stop(self):
        if self._closed:
            if self._cleanup_errors:
                raise RuntimeError('Lần dừng trước chưa xác nhận được phần cứng đã an toàn.')
            return
        self._closed = True
        errors = []
        # Attempt every cleanup even if one device fails.
        for device in (self._motor, self._hand, self._matrix):
            if device is not None:
                try:
                    device.close()
                except Exception as error:
                    errors.append(error)
        if errors:
            self._cleanup_errors = errors
            print(json.dumps({'event': 'unsafe_stop', 'message': f'Lỗi dừng thiết bị: {errors!s}'},
                             ensure_ascii=False), flush=True)
            raise errors[0]


def close_all():
    errors = []
    while _robots:
        try:
            _robots.pop().stop()
        except Exception as error:
            errors.append(error)
    return errors

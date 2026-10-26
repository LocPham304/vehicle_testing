"""Draft Mecanum moves and arm commands, then enter 'chay' to run."""

import argparse
import logging
import sys
from pathlib import Path


# Support both `python vehicle_testing/main.py` and `python -m vehicle_testing.main`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehicle_testing.config import DEFAULT_SPEED, TURN_SPEED, SERVO_BCM_PIN, CLAW_BCM_PIN
from vehicle_testing.hand import (
    DryRunServoOutput, GPIOServoOutput, HandController, ClawController,
    validate_hand_angle, validate_hand_step,
)
from vehicle_testing.controller import (
    DryRunOutput,
    MotorController,
    PCA9685Output,
    validate_duration,
    validate_motion,
    validate_speed,
    validate_strafe,
    validate_turn,
)


logger = logging.getLogger(__name__)
TIMED_COMMANDS = {
    "tien": "forward", "lui": "backward",
    "ngang_trai": "strafe_left", "ngang_phai": "strafe_right",
    "tren_trai": "forward_left",
    "tren_phai": "forward_right",
    "duoi_trai": "backward_left", "duoi_phai": "backward_right",
}
TIMED_LABELS = {action: command for command, action in TIMED_COMMANDS.items()}
HAND_COMMANDS = {"nang": "hand_up", "ha": "hand_down", "tay_goc": "hand_angle"}
HAND_LABELS = {action: command for command, action in HAND_COMMANDS.items()}
CLAW_COMMANDS = {"cang_goc": "claw_angle", "mo_cang": "claw_open", "dong_cang": "claw_grip"}
CLAW_LABELS = {action: command for command, action in CLAW_COMMANDS.items()}
HELP = f"""Lenh:
  tien <giay> [PWM]   Them lenh tien, vi du: tien 2
  lui  <giay> [PWM]   Them lenh lui, vi du: lui 1 0.3
  ngang_trai <giay> [PWM]  Truot ngang trai, vi du: ngang_trai 0.5 0.3
  ngang_phai <giay> [PWM]  Truot ngang phai, vi du: ngang_phai 0.5
  tren_trai <giay> [PWM]  Di len trai 45 do, vi du: tren_trai 0.5 0.3
  tren_phai <giay> [PWM]  Di len phai 45 do, vi du: tren_phai 0.5 0.3
  duoi_trai <giay> [PWM]  Di lui trai 45 do, vi du: duoi_trai 0.5 0.3
  duoi_phai <giay> [PWM]  Di lui phai 45 do, vi du: duoi_phai 0.5 0.3
  trai <do>           Quay tai cho sang trai, vi du: trai 15
  phai <do>           Quay tai cho sang phai, vi du: phai 90
  tay_goc <do>       Dat goc tay tuyet doi 0..80, vi du: tay_goc 40
  nang <do>          Nang tay: giam goc tuong doi, vi du: nang 10
  ha <do>            Ha tay: tang goc tuong doi, vi du: ha 10
  cang_goc <do>      Dat goc cang tuyet doi 0..80, vi du: cang_goc 40
  mo_cang <do>       Mo cang: giam goc tuong doi, vi du: mo_cang 10
  dong_cang <do>     Khep cang: tang goc tuong doi, vi du: dong_cang 10
  ngung <giay>       Them khoang nghi, vi du: ngung 0.5
  chay               Thuc hien kich ban da nhap
  dung               Gui lenh dung va huy kich ban dang soan
  thoat              Huy kich ban dang soan, dung va thoat
Bo trong PWM thi moi lenh dung {DEFAULT_SPEED:.0%}. PWM trong (0, 1].
Lenh quay dung PWM co dinh {TURN_SPEED:.0%}, khong nhan PWM rieng.
Goc quay chi UOC LUONG theo thoi gian; can hieu chinh he so trong config.py.
Chay tay_goc truoc nang/ha. Nang/ha dung GPIO BCM {SERVO_BCM_PIN}, gioi han 0..80 do.
Chay cang_goc truoc mo_cang/dong_cang. Cang dung GPIO BCM {CLAW_BCM_PIN}, gioi han 0..80 do.
Tay giu PWM sau moi lenh; thoat/Ctrl+C se tat PWM servo.
Enter chi luu lenh. Nhap du cac dong roi go chay va nhan Enter.
Chay xong thi xoa danh sach. Co the nhap kich ban moi.
Khi dang chay, nhan Ctrl+C de dung va thoat.
"""


def parse_command(line: str) -> tuple[str, float, float]:
    """Return (action, seconds_or_degrees, pwm); arm commands have no PWM argument."""
    parts = line.lower().split()
    controls = {"chay": "run", "dung": "stop", "thoat": "exit"}
    if len(parts) == 1 and parts[0] in controls:
        return controls[parts[0]], 0.0, 0.0
    if len(parts) == 2 and parts[0] in (HAND_COMMANDS | CLAW_COMMANDS):
        try:
            angle = float(parts[1])
        except ValueError as error:
            raise ValueError("Goc tay phai la so, vi du: nang 10 hoac tay_goc 40.") from error
        if parts[0] in ("tay_goc", "cang_goc"):
            validate_hand_angle(angle)
        else:
            validate_hand_step(angle)
        return (HAND_COMMANDS | CLAW_COMMANDS)[parts[0]], angle, 0.0
    if len(parts) == 2 and parts[0] == "ngung":
        try:
            seconds = float(parts[1])
        except ValueError as error:
            raise ValueError("Thoi gian ngung phai la so, vi du: ngung 0.5.") from error
        validate_duration(seconds)
        return "pause", seconds, 0.0
    if len(parts) == 2 and parts[0] in ("trai", "phai"):
        try:
            angle = float(parts[1])
        except ValueError as error:
            raise ValueError("Goc quay phai la so, vi du: trai 15.5.") from error
        direction = "left" if parts[0] == "trai" else "right"
        validate_turn(direction, angle)
        return direction, angle, TURN_SPEED
    if len(parts) not in (2, 3) or parts[0] not in TIMED_COMMANDS:
        raise ValueError(f"Dung cu phap: {'/'.join(TIMED_COMMANDS)} <giay> [PWM], trai/phai <do>, nang/ha/tay_goc/mo_cang/dong_cang/cang_goc <do>, ngung <giay>, chay, dung, hoac thoat.")
    try:
        seconds = float(parts[1])
        speed = float(parts[2]) if len(parts) == 3 else DEFAULT_SPEED
    except ValueError as error:
        raise ValueError("Thoi gian va PWM phai la so; dung dau cham cho so thap phan.") from error
    direction = TIMED_COMMANDS[parts[0]]
    if direction in ("strafe_left", "strafe_right"):
        validate_strafe(direction.removeprefix("strafe_"), seconds, speed)
    elif direction in ("forward_left", "forward_right", "backward_left", "backward_right"):
        validate_duration(seconds)
        validate_speed(speed)
    else:
        validate_motion(direction, seconds, speed)
    return direction, seconds, speed


def run_session(controller: MotorController, hand: HandController | None = None,
                claw: ClawController | None = None) -> None:
    print(HELP)
    pending: list[tuple[str, float, float]] = []
    while True:
        try:
            line = input("robot> ")
        except EOFError:
            return
        if not line.strip():
            continue
        try:
            action, value, speed = parse_command(line)
        except ValueError as error:
            logger.warning("Lenh khong hop le: %s", error)
            continue
        if action == "exit":
            return
        if action == "stop":
            controller.stop()
            pending.clear()
            logger.info("Da gui lenh dung cac motor va huy kich ban dang soan.")
        elif action == "run":
            if not pending:
                logger.info("Kich ban dang rong. Nhap lenh %s/trai/phai/ngung truoc khi chay.", "/".join(TIMED_COMMANDS))
                continue
            # Consume the script before execution so it cannot replay on error.
            script, pending = pending, []
            logger.info("Bat dau kich ban: %d lenh.", len(script))
            for index, (step, amount, pwm) in enumerate(script, start=1):
                logger.info("Thuc hien lenh %d/%d.", index, len(script))
                if step in CLAW_LABELS:
                    controller.stop()
                    if claw is None:
                        raise RuntimeError("Chua cau hinh bo dieu khien cang.")
                    if step == "claw_angle":
                        claw.set_angle(amount)
                    elif step == "claw_open":
                        claw.open(amount)
                    else:
                        claw.grip(amount)
                elif step in HAND_LABELS:
                    controller.stop()
                    if hand is None:
                        raise RuntimeError("Chua cau hinh bo dieu khien tay.")
                    if step == "hand_angle":
                        hand.set_angle(amount)
                    elif step == "hand_up":
                        hand.hand_up(amount)
                    else:
                        hand.hand_down(amount)
                elif step == "pause":
                    controller.pause(amount)
                elif step == "left":
                    controller.turn_left(amount)
                elif step == "right":
                    controller.turn_right(amount)
                elif step in ("strafe_left", "strafe_right"):
                    controller.strafe(step.removeprefix("strafe_"), amount, pwm)
                elif step == "forward_left":
                    controller.move_forward_left(amount, pwm)
                elif step == "forward_right":
                    controller.move_forward_right(amount, pwm)
                elif step == "backward_left":
                    controller.move_backward_left(amount, pwm)
                elif step == "backward_right":
                    controller.move_backward_right(amount, pwm)
                else:
                    controller.move(step, amount, pwm)
            logger.info("Da hoan tat kich ban. Co the nhap kich ban moi.")
        else:
            pending.append((action, value, speed))
            if action in (HAND_LABELS | CLAW_LABELS):
                logger.info("Da luu lenh #%d: %s %g do. Go chay de bat dau.",
                            len(pending), (HAND_LABELS | CLAW_LABELS)[action], value)
            elif action == "pause":
                logger.info("Da luu lenh #%d: ngung %g giay. Go chay de bat dau.", len(pending), value)
            elif action in ("left", "right"):
                label = "trai" if action == "left" else "phai"
                logger.info(
                    "Da luu lenh #%d: quay %s %g do (uoc luong), PWM %.0f%%. Go chay de bat dau.",
                    len(pending), label, value, TURN_SPEED * 100,
                )
            else:
                label = TIMED_LABELS[action]
                logger.info(
                    "Da luu lenh #%d: %s %g giay, PWM %.0f%%. Go chay de bat dau.",
                    len(pending), label, value, speed * 100,
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Mo phong, khong ket noi phan cung")
    parser.add_argument("--verbose", action="store_true", help="Hien chi tiet tung kenh dieu khien")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s", stream=sys.stdout,
    )

    controller = None
    output = None
    hand = None
    claw = None
    result = 0
    try:
        logger.info("MO PHONG - khong dieu khien phan cung" if args.dry_run else "CHE DO PHAN CUNG")
        output = DryRunOutput() if args.dry_run else PCA9685Output()
        controller = MotorController(output)
        hand = HandController(DryRunServoOutput if args.dry_run else GPIOServoOutput)
        claw_output = DryRunServoOutput if args.dry_run else GPIOServoOutput
        claw = ClawController(lambda: claw_output(pin=CLAW_BCM_PIN))
        controller.stop()
        run_session(controller, hand, claw)
    except KeyboardInterrupt:
        logger.info("Nhan Ctrl+C, dang gui lenh dung...")
        result = 130
    except Exception as error:
        logger.error("Khong the tiep tuc: %s", error)
        result = 1
    finally:
        try:
            try:
                if controller is not None:
                    controller.close()
                elif output is not None:
                    output.close()
            except KeyboardInterrupt:
                logger.info("Ngat khi dong motor; tiep tuc tat PWM servo.")
                result = 130
            except Exception as error:
                logger.error("Loi khi dung/giai phong phan cung: %s", error)
                result = 1
        finally:
            # Always attempt servo cleanup, even if motor cleanup is interrupted.
            for servo in (hand, claw):
                try:
                    if servo is not None:
                        servo.close()
                except KeyboardInterrupt:
                    logger.info("Ngat khi giai phong servo; tiep tuc don cac servo con lai.")
                    result = 130
                except Exception as error:
                    logger.error("Loi khi tat/giai phong servo: %s", error)
                    result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())

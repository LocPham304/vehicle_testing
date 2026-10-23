"""Draft timed movement commands, then enter 'chay' to run the script."""

import argparse
import logging
import sys
from pathlib import Path


# Support both `python stem_project/main.py` and `python -m stem_project.main`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stem_project.config import DEFAULT_SPEED
from stem_project.controller import (
    DryRunOutput,
    MotorController,
    PCA9685Output,
    validate_duration,
    validate_motion,
)


logger = logging.getLogger(__name__)
HELP = f"""Lenh:
  tien <giay> [PWM]   Them lenh tien, vi du: tien 2
  lui  <giay> [PWM]   Them lenh lui, vi du: lui 1 0.3
  ngung <giay>       Them khoang nghi, vi du: ngung 0.5
  chay               Thuc hien kich ban da nhap
  dung               Gui lenh dung va huy kich ban dang soan
  thoat              Huy kich ban dang soan, dung va thoat
Bo trong PWM thi moi lenh dung {DEFAULT_SPEED:.0%}. PWM trong (0, 1].
Enter chi luu lenh. Nhap du cac dong roi go chay va nhan Enter.
Chay xong thi xoa danh sach. Co the nhap kich ban moi.
Khi dang chay, nhan Ctrl+C de dung va thoat.
"""


def parse_command(line: str) -> tuple[str, float, float]:
    parts = line.lower().split()
    controls = {"chay": "run", "dung": "stop", "thoat": "exit"}
    if len(parts) == 1 and parts[0] in controls:
        return controls[parts[0]], 0.0, 0.0
    if len(parts) == 2 and parts[0] == "ngung":
        try:
            seconds = float(parts[1])
        except ValueError as error:
            raise ValueError("Thoi gian ngung phai la so, vi du: ngung 0.5.") from error
        validate_duration(seconds)
        return "pause", seconds, 0.0
    if len(parts) not in (2, 3) or parts[0] not in ("tien", "lui"):
        raise ValueError("Dung cu phap: tien/lui <giay> [PWM], ngung <giay>, chay, dung, hoac thoat.")
    try:
        seconds = float(parts[1])
        speed = float(parts[2]) if len(parts) == 3 else DEFAULT_SPEED
    except ValueError as error:
        raise ValueError("Thoi gian va PWM phai la so; dung dau cham cho so thap phan.") from error
    direction = "forward" if parts[0] == "tien" else "backward"
    validate_motion(direction, seconds, speed)
    return direction, seconds, speed


def run_session(controller: MotorController) -> None:
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
            action, seconds, speed = parse_command(line)
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
                logger.info("Kich ban dang rong. Nhap lenh tien/lui/ngung truoc khi chay.")
                continue
            # Consume the script before execution so it cannot replay on error.
            script, pending = pending, []
            logger.info("Bat dau kich ban: %d lenh.", len(script))
            for index, (step, duration, pwm) in enumerate(script, start=1):
                logger.info("Thuc hien lenh %d/%d.", index, len(script))
                if step == "pause":
                    controller.pause(duration)
                else:
                    controller.move(step, duration, pwm)
            logger.info("Da hoan tat kich ban. Co the nhap kich ban moi.")
        else:
            pending.append((action, seconds, speed))
            if action == "pause":
                logger.info("Da luu lenh #%d: ngung %g giay. Go chay de bat dau.", len(pending), seconds)
            else:
                label = "tien" if action == "forward" else "lui"
                logger.info(
                    "Da luu lenh #%d: %s %g giay, PWM %.0f%%. Go chay de bat dau.",
                    len(pending), label, seconds, speed * 100,
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
    result = 0
    try:
        logger.info("MO PHONG - khong dieu khien phan cung" if args.dry_run else "CHE DO PHAN CUNG")
        output = DryRunOutput() if args.dry_run else PCA9685Output()
        controller = MotorController(output)
        controller.stop()
        run_session(controller)
    except KeyboardInterrupt:
        logger.info("Nhan Ctrl+C, dang gui lenh dung...")
        result = 130
    except Exception as error:
        logger.error("Khong the tiep tuc: %s", error)
        result = 1
    finally:
        try:
            if controller is not None:
                controller.close()
            elif output is not None:
                output.close()
        except Exception as error:
            logger.error("Loi khi dung/giai phong phan cung: %s", error)
            result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())

"""Child process for generated programs; supplies the controlled robot_sdk import."""

import argparse
import logging
from pathlib import Path
import runpy
import signal
import sys
import traceback

from vehicle_testing import robot_sdk


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', required=True, type=Path)
    parser.add_argument('--stop-file', type=Path)
    parser.add_argument('--speed', type=float, default=0.25)
    parser.add_argument('--lift-start-lowered', action='store_true')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--run', action='store_true')
    mode.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stdout)
    robot_sdk.configure(dry_run=not args.run, stop_file=args.stop_file, speed=args.speed,
                        lift_start_lowered=args.lift_start_lowered)
    sys.modules['robot_sdk'] = robot_sdk

    def stop(signum, frame):
        raise robot_sdk.RobotStopped('Đã nhận tín hiệu dừng.')

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    result = 0
    try:
        runpy.run_path(str(args.file.resolve()), run_name='__main__')
    except robot_sdk.RobotStopped as error:
        logging.info('%s', error)
        result = 130
    except BaseException:
        traceback.print_exc()
        result = 1
    finally:
        errors = robot_sdk.close_all()
        if errors:
            logging.error('Không đóng được toàn bộ thiết bị: %s', errors)
            result = 1
    return result


if __name__ == '__main__':
    raise SystemExit(main())

"""Windows Bluetooth COM console: python bluetooth_client.py."""

import argparse
import sys

from vehicle_testing.connections.usb.client import USBClient
from vehicle_testing.runtime.console import run_console


class BluetoothClient(USBClient):
    """SPP carries the same stream protocol as USB; no duplicate request logic."""
    def __init__(self, connection, *, notify=None):
        super().__init__(connection, notify=notify, transport="Bluetooth")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="COM Outgoing Bluetooth cua Pi, vi du COM8")
    parser.add_argument("--list", action="store_true", help="Liet ke COM; chua mo ket noi")
    args = parser.parse_args(argv)
    try:
        import serial
        from serial.tools import list_ports
    except ImportError:
        print("Cai: python -m pip install -r requirements-bluetooth.txt")
        return 1
    if args.list or not args.port:
        ports = list(list_ports.comports())
        for index, port in enumerate(ports, 1):
            print(f"{index}. {port.device}: {port.description}")
        if args.list:
            return 0
        if not ports:
            print("Chua co COM. Ghep doi Bluetooth voi Pi va them COM Outgoing cho dich vu SPP.")
            return 1
        print("Chon COM Outgoing Bluetooth cua Pi; danh sach co the gom ca cong USB khac.")
        try:
            index = int(input("So thu tu COM Bluetooth: "))
            if not 1 <= index <= len(ports):
                raise ValueError
            args.port = ports[index - 1].device
        except (ValueError, EOFError):
            print("So thu tu khong hop le.")
            return 1
        except KeyboardInterrupt:
            return 130
    connection = client = None
    try:
        # Baud is a serial API setting; RFCOMM radio speed is negotiated by Bluetooth.
        connection = serial.serial_for_url(args.port, baudrate=115200, timeout=0.1, write_timeout=2)
        connection.reset_input_buffer()
        client = BluetoothClient(connection)
        client.start()
        print("Pi:", client.request("status"))
        run_console(client, prompt="bt> ")
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, serial.SerialException) as error:
        print(f"Loi Bluetooth: {error}")
        return 1
    finally:
        if client is not None:
            client.close()
        elif connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())

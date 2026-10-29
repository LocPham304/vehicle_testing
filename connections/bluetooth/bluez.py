"""BlueZ Profile1 bridge. Pi-only dependencies are loaded only at startup."""

import logging
import os
import socket


SPP_UUID = "00001101-0000-1000-8000-00805f9b34fb"
PROFILE_PATH = "/vn/stem/robot/serial"
logger = logging.getLogger(__name__)


def load_dependencies():
    try:
        import dbus
        import dbus.service
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib
    except ImportError as error:
        raise RuntimeError("Tren Pi cai: sudo apt install bluez python3-dbus python3-gi; "
                           "venv can --system-site-packages. Xem docs/BLUETOOTH.md.") from error
    return dbus, DBusGMainLoop, GLib


def build_profile(bus, receiver, loop, dbus):
    class Rejected(dbus.DBusException):
        _dbus_error_name = "org.bluez.Error.Rejected"

    class Profile(dbus.service.Object):
        released = False

        @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
        def Release(self):
            self.released = True
            receiver.disconnect()
            loop.quit()

        @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}", out_signature="")
        def NewConnection(self, device, fd, properties):
            raw_fd = fd.take()
            try:
                try:
                    connection = socket.socket(fileno=raw_fd)
                except OSError:
                    os.close(raw_fd)
                    raise
                # accept takes ownership on both success and rejection.
                receiver.accept(str(device), connection)
            except (OSError, RuntimeError) as error:
                raise Rejected(str(error)) from error

        @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
        def RequestDisconnection(self, device):
            receiver.disconnect(str(device))

    return Profile(bus, PROFILE_PATH)


def run_profile(receiver, *, channel=3):
    dbus, DBusGMainLoop, GLib = load_dependencies()
    DBusGMainLoop(set_as_default=True)
    bus = profile = manager = None
    registered = False
    lost = []
    try:
        bus = dbus.SystemBus(private=True)
        objects = dbus.Interface(bus.get_object("org.bluez", "/"),
                                 "org.freedesktop.DBus.ObjectManager").GetManagedObjects()
        adapters = [interfaces["org.bluez.Adapter1"] for interfaces in objects.values()
                    if "org.bluez.Adapter1" in interfaces]
        if not adapters:
            raise RuntimeError("Khong thay Bluetooth adapter tren Pi; kiem tra bluetoothctl list va rfkill.")
        if not any(adapter.get("Powered", False) for adapter in adapters):
            raise RuntimeError("Bluetooth adapter chua bat; dung bluetoothctl power on va kiem tra rfkill.")
        loop = GLib.MainLoop()
        profile = build_profile(bus, receiver, loop, dbus)
        manager = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"), "org.bluez.ProfileManager1")

        def daemon_changed(name, old_owner, new_owner):
            if old_owner and old_owner != new_owner:
                profile.released = True
                lost.append("BlueZ da dung/khoi dong lai; khoi dong lai bluetooth_receiver.py.")
                receiver.disconnect()
                loop.quit()

        def bus_lost(*args):
            profile.released = True
            lost.append("Mat system D-Bus; khoi dong lai receiver sau khi dich vu phuc hoi.")
            receiver.disconnect()
            loop.quit()

        bus.add_signal_receiver(daemon_changed, signal_name="NameOwnerChanged",
                                dbus_interface="org.freedesktop.DBus", arg0="org.bluez")
        bus.call_on_disconnection(bus_lost)
        manager.RegisterProfile(PROFILE_PATH, SPP_UUID, {
            "Name": "STEM Robot Serial", "Role": "server", "Channel": dbus.UInt16(channel),
            "RequireAuthentication": True, "RequireAuthorization": True,
        })
        registered = True
        logger.info("Da dang ky SPP. Ghep doi laptop voi Pi, chon COM Outgoing cua STEM Robot Serial.")
        loop.run()
        if lost:
            raise RuntimeError(lost[0])
    except dbus.DBusException as error:
        raise RuntimeError(f"BlueZ/D-Bus: {error}. Kiem tra bluetooth.service, radio va quyen D-Bus.") from error
    finally:
        receiver.disconnect()
        if registered and not profile.released:
            try:
                manager.UnregisterProfile(PROFILE_PATH)
            except dbus.DBusException as error:
                logger.warning("Khong unregister duoc SPP: %s", error)
        if profile is not None:
            profile.remove_from_connection()
        if bus is not None:
            bus.close()

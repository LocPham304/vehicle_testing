from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from vehicle_testing.connections.bluetooth import bluez


class FakeObject:
    def __init__(self, *args):
        pass


class FakeDBusError(Exception):
    pass


class BlueZProfileTests(unittest.TestCase):
    def setUp(self):
        self.dbus = SimpleNamespace(service=SimpleNamespace(
            Object=FakeObject, method=lambda *a, **k: lambda f: f), DBusException=FakeDBusError)
        self.receiver, self.loop = Mock(), Mock()
        self.profile = bluez.build_profile(Mock(), self.receiver, self.loop, self.dbus)

    def test_socket_is_taken_from_bluez_fd_then_owned_by_receiver(self):
        fd, connection = Mock(), Mock()
        fd.take.return_value = 73
        with patch.object(bluez.socket, "socket", return_value=connection) as factory:
            self.profile.NewConnection("/laptop", fd, {})
        fd.take.assert_called_once_with()
        factory.assert_called_once_with(fileno=73)
        self.receiver.accept.assert_called_once_with("/laptop", connection)

    def test_socket_construction_failure_closes_taken_fd_and_rejects(self):
        fd = Mock()
        fd.take.return_value = 73
        with patch.object(bluez.socket, "socket", side_effect=OSError("bad fd")), \
                patch.object(bluez.os, "close") as close:
            with self.assertRaises(FakeDBusError):
                self.profile.NewConnection("/laptop", fd, {})
        close.assert_called_once_with(73)

    def test_busy_receiver_becomes_bluez_rejected_without_reclosing_fd(self):
        self.receiver.accept.side_effect = RuntimeError("busy")
        with patch.object(bluez.socket, "socket", return_value=Mock()), patch.object(bluez.os, "close") as close:
            with self.assertRaises(FakeDBusError):
                self.profile.NewConnection("/other", Mock(), {})
        close.assert_not_called()  # receiver.accept already owns/closes socket

    def test_disconnect_and_release_delegate_cleanup_without_joining_in_callback(self):
        self.profile.RequestDisconnection("/laptop")
        self.receiver.disconnect.assert_called_once_with("/laptop")
        self.profile.Release()
        self.assertTrue(self.profile.released)
        self.loop.quit.assert_called_once_with()
        self.receiver.close.assert_not_called()

    def test_registration_advertises_standard_spp_requires_pairing_and_unregisters(self):
        bus, manager, profile = Mock(), Mock(), Mock(released=False)
        manager.GetManagedObjects.return_value = {"/org/bluez/hci0": {"org.bluez.Adapter1": {"Powered": True}}}
        dbus = SimpleNamespace(SystemBus=Mock(return_value=bus), Interface=Mock(return_value=manager),
                               UInt16=int, DBusException=FakeDBusError)
        glib = SimpleNamespace(MainLoop=Mock(return_value=self.loop))
        with patch.object(bluez, "load_dependencies", return_value=(dbus, Mock(), glib)), \
                patch.object(bluez, "build_profile", return_value=profile):
            bluez.run_profile(self.receiver, channel=3)
        args = manager.RegisterProfile.call_args.args
        self.assertEqual(args[1], "00001101-0000-1000-8000-00805f9b34fb")
        self.assertTrue(args[2]["RequireAuthentication"])
        self.assertTrue(args[2]["RequireAuthorization"])
        self.assertEqual(args[2]["Channel"], 3)
        manager.UnregisterProfile.assert_called_once_with(bluez.PROFILE_PATH)
        profile.remove_from_connection.assert_called_once_with()
        bus.close.assert_called_once_with()

    def test_lost_bluez_daemon_stops_receiver_and_exits_instead_of_false_ready(self):
        bus, manager, profile = Mock(), Mock(), Mock(released=False)
        manager.GetManagedObjects.return_value = {"/org/bluez/hci0": {"org.bluez.Adapter1": {"Powered": True}}}
        dbus = SimpleNamespace(SystemBus=Mock(return_value=bus), Interface=Mock(return_value=manager),
                               UInt16=int, DBusException=FakeDBusError)
        glib = SimpleNamespace(MainLoop=Mock(return_value=self.loop))

        def lose_daemon():
            callback = bus.add_signal_receiver.call_args.args[0]
            callback("org.bluez", ":1.7", "")

        self.loop.run.side_effect = lose_daemon
        with patch.object(bluez, "load_dependencies", return_value=(dbus, Mock(), glib)), \
                patch.object(bluez, "build_profile", return_value=profile), self.assertRaises(RuntimeError):
            bluez.run_profile(self.receiver)
        self.receiver.disconnect.assert_called()
        manager.UnregisterProfile.assert_not_called()
        bus.close.assert_called_once_with()

    def test_missing_or_powered_off_adapter_does_not_advertise_false_ready(self):
        for objects in ({}, {"/org/bluez/hci0": {"org.bluez.Adapter1": {"Powered": False}}}):
            with self.subTest(objects=objects):
                bus, manager = Mock(), Mock()
                manager.GetManagedObjects.return_value = objects
                dbus = SimpleNamespace(SystemBus=Mock(return_value=bus), Interface=Mock(return_value=manager),
                                       UInt16=int, DBusException=FakeDBusError)
                with patch.object(bluez, "load_dependencies", return_value=(dbus, Mock(), Mock())), \
                        patch.object(bluez, "build_profile", return_value=Mock(released=False)), \
                        self.assertRaises(RuntimeError):
                    bluez.run_profile(self.receiver)
                manager.RegisterProfile.assert_not_called()
                bus.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

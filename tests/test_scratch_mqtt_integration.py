"""Optional loopback test with real Mosquitto/Paho and simulated hardware."""

import importlib.util
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
from threading import Event
import time
import unittest

from vehicle_testing.scratch_receiver import ScratchReceiver, create_client
from vehicle_testing.scratch_runner import execute_program


MOSQUITTO = shutil.which("mosquitto")
if MOSQUITTO is None and Path("C:/Program Files/mosquitto/mosquitto.exe").is_file():
    MOSQUITTO = "C:/Program Files/mosquitto/mosquitto.exe"
HAS_PAHO = importlib.util.find_spec("paho") is not None


@unittest.skipUnless(MOSQUITTO and HAS_PAHO, "Needs local Mosquitto and paho-mqtt")
class MQTTIntegrationTests(unittest.TestCase):
    def test_real_broker_upload_execute_and_status_with_simulated_hardware(self):
        import paho.mqtt.client as mqtt
        from paho.mqtt.publish import multiple

        with tempfile.TemporaryDirectory() as folder:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            config = Path(folder) / "mosquitto.conf"
            config.write_text(f"listener {port} 127.0.0.1\nallow_anonymous true\npersistence false\n", encoding="utf-8")
            broker = subprocess.Popen([MOSQUITTO, "-c", str(config)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.addCleanup(self.stop_broker, broker)
            deadline = time.monotonic() + 5
            while True:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    if broker.poll() is not None or time.monotonic() > deadline:
                        self.fail("Local test broker did not start")
                    Event().wait(0.02)

            statuses, received = [], []
            done, subscribed, observed = Event(), Event(), Event()

            def execute(program, *, stop_event):
                received.append(program)
                execute_program(program, dry_run=True, stop_event=stop_event)

            receiver = ScratchReceiver("integration-only", executor=execute)
            client = create_client(receiver)
            self.addCleanup(client.loop_stop)
            self.addCleanup(client.disconnect)
            self.addCleanup(receiver.close)

            original_subscribe = client.on_subscribe

            def on_subscribe(*args):
                original_subscribe(*args)
                subscribed.set()

            client.on_subscribe = on_subscribe
            observer = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="integration-observer")
            self.addCleanup(observer.loop_stop)
            self.addCleanup(observer.disconnect)
            observer.on_connect = lambda c, u, f, r, p: c.subscribe("device/integration-only/status", qos=1)
            observer.on_subscribe = lambda *args: observed.set()

            def on_status(c, u, message):
                statuses.append(message.payload.decode("utf-8"))
                if statuses[-1] == "done":
                    done.set()

            observer.on_message = on_status
            observer.connect("127.0.0.1", port)
            observer.loop_start()
            client.connect("127.0.0.1", port)
            client.loop_start()
            self.assertTrue(observed.wait(3))
            self.assertTrue(subscribed.wait(3))
            # Deliberately differs from scratch_sample.txt: never fall back to a file.
            source = 'report_block("network-only")\nrobot.sendCmd("turn_right:1")\nrobot.sendCmd("led_strip:MQTT OK")'
            multiple([
                {"topic": "device/integration-only/code", "payload": source, "qos": 1},
                {"topic": "device/integration-only/execute", "payload": "execute", "qos": 1},
            ], hostname="127.0.0.1", port=port)
            self.assertTrue(done.wait(3), statuses)
            self.assertTrue(receiver.wait_for_execution(2))
            self.assertEqual(statuses, ["executing", "done"])
            self.assertEqual(received[0].events[0].block_id, "network-only")
            self.assertEqual(received[0].events[-1].value, "MQTT OK")

    @staticmethod
    def stop_broker(broker):
        broker.terminate()
        try:
            broker.wait(timeout=3)
        except subprocess.TimeoutExpired:
            broker.kill()
            broker.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()

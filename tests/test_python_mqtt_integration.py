"""Real loopback MQTT broker -> converter -> saved Python -> child SDK dry-run."""

import json
from pathlib import Path
import socket
import subprocess
import tempfile
from threading import Event
import time
import unittest

from vehicle_testing.connections.mqtt.python_receiver import PythonMqttReceiver
from vehicle_testing.connections.mqtt.receiver import create_client
from vehicle_testing.tests.test_scratch_mqtt_integration import MOSQUITTO, HAS_PAHO


@unittest.skipUnless(MOSQUITTO and HAS_PAHO, 'Needs local Mosquitto and paho-mqtt')
class PythonMqttIntegrationTests(unittest.TestCase):
    def test_actual_mqtt_upload_convert_child_execute_and_block_feedback(self):
        import paho.mqtt.client as mqtt

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            config = folder / 'mosquitto.conf'
            config.write_text(f'listener {port} 127.0.0.1\nallow_anonymous true\npersistence false\n', encoding='utf-8')
            broker = subprocess.Popen([MOSQUITTO, '-c', str(config)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.addCleanup(self.stop_broker, broker)
            deadline = time.monotonic() + 5
            while True:
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                        break
                except OSError:
                    if broker.poll() is not None or time.monotonic() >= deadline:
                        self.fail('Loopback MQTT broker did not start')
                    Event().wait(0.02)

            receiver = PythonMqttReceiver('python-integration', program_dir=folder / 'programs', dry_run=True)
            client = create_client(receiver)
            subscribed = Event()
            callback = client.on_subscribe

            def on_subscribe(*args):
                callback(*args)
                subscribed.set()

            client.on_subscribe = on_subscribe
            self.addCleanup(client.loop_stop)
            self.addCleanup(client.disconnect)
            self.addCleanup(receiver.close)

            observed, uploaded, done = Event(), Event(), Event()
            statuses, blocks = [], []
            observer = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='python-observer')
            self.addCleanup(observer.loop_stop)
            self.addCleanup(observer.disconnect)
            observer.on_connect = lambda c, u, f, r, p: c.subscribe('device/python-integration/#', qos=1)
            observer.on_subscribe = lambda *args: observed.set()

            def on_message(c, u, message):
                text = message.payload.decode('utf-8')
                if message.topic.endswith('/status'):
                    statuses.append(text)
                    if text == 'uploaded':
                        uploaded.set()
                    if text == 'done':
                        done.set()
                elif message.topic.endswith('/block'):
                    blocks.append(json.loads(text)['block_id'])

            observer.on_message = on_message
            observer.connect('127.0.0.1', port)
            observer.loop_start()
            client.connect('127.0.0.1', port)
            client.loop_start()
            self.assertTrue(observed.wait(3))
            self.assertTrue(subscribed.wait(3))
            source = ('report_block("from-backend-format") robot.sendCmd("move_forward:0.1")\n'
                      'report_block("lift") robot.sendCmd("hand_up:30")\nrobot.sendCmd("led_strip:MQTT OK")')
            observer.publish(receiver.topic_code, source, qos=1).wait_for_publish(timeout=3)
            self.assertTrue(uploaded.wait(3), statuses)
            self.assertFalse(receiver.busy)
            files = list((folder / 'programs').glob('*.py'))
            self.assertEqual(len(files), 1)
            self.assertIn('robot.hand_up(30.0)', files[0].read_text(encoding='utf-8'))
            observer.publish(receiver.topic_execute, 'execute', qos=1).wait_for_publish(timeout=3)
            self.assertTrue(done.wait(8), statuses)
            self.assertTrue(receiver.wait_for_execution(3))
            self.assertEqual(statuses, ['uploaded', 'executing', 'done'])
            self.assertEqual(blocks, ['from-backend-format', 'lift'])

    @staticmethod
    def stop_broker(broker):
        if broker.poll() is None:
            broker.terminate()
            try:
                broker.wait(timeout=3)
            except subprocess.TimeoutExpired:
                broker.kill()
                broker.wait(timeout=3)

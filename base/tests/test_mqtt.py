import unittest
from os import environ
from pathlib import Path
from sys import path as sys_path
from unittest.mock import Mock
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
sys_path.insert(0, str(BASE / "root" / "scripts"))

# pylint: disable=wrong-import-position
from includes.mqtt import mqtt_auth  # noqa: E402
from includes.mqtt import publish  # noqa: E402
from includes.mqtt import settings  # noqa: E402


class MqttTests(unittest.TestCase):
    def test_auth_requires_both_credentials(self):
        self.assertIsNone(mqtt_auth(None, None))
        self.assertIsNone(mqtt_auth("station", None))
        self.assertIsNone(mqtt_auth(None, "secret"))
        self.assertEqual(
            mqtt_auth("station", "secret"),
            {"username": "station", "password": "secret"},
        )

    def test_settings_read_the_broker_from_the_environment(self):
        with patch.dict(
            environ,
            {
                "MQTT_SERVER": "mqtt.example",
                "MQTT_SERVER_PORT": "1884",
                "MQTT_USERNAME": "station",
                "MQTT_PASSWORD": "secret",
            },
        ):
            chosen = settings()

        self.assertEqual(chosen["hostname"], "mqtt.example")
        self.assertEqual(chosen["port"], 1884)
        self.assertEqual(chosen["auth"], {"username": "station", "password": "secret"})

    def test_settings_omit_auth_when_a_credential_is_missing(self):
        with patch.dict(environ, {"MQTT_USERNAME": "station"}, clear=False):
            environ.pop("MQTT_PASSWORD", None)
            chosen = settings()

        self.assertIsNone(chosen["auth"])

    def test_publish_passes_the_broker_and_keeps_the_message(self):
        single = Mock()
        protocol = object()
        with patch.dict(
            environ,
            {"MQTT_SERVER": "mqtt.example", "MQTT_SERVER_PORT": "1883"},
            clear=False,
        ):
            environ.pop("MQTT_USERNAME", None)
            environ.pop("MQTT_PASSWORD", None)
            publish("weather", "payload", single=single, protocol=protocol)

        self.assertEqual(single.call_args.args[0], "weather")
        self.assertEqual(single.call_args.kwargs["payload"], "payload")
        self.assertEqual(single.call_args.kwargs["hostname"], "mqtt.example")
        self.assertEqual(single.call_args.kwargs["port"], 1883)
        self.assertIsNone(single.call_args.kwargs["auth"])
        self.assertIs(single.call_args.kwargs["protocol"], protocol)
        self.assertTrue(single.call_args.kwargs["retain"])
        self.assertEqual(single.call_args.kwargs["qos"], 0)

import json
import time
import unittest
from os import environ
from pathlib import Path
from unittest.mock import patch

from tests.load_scripts import load
from tests.load_scripts import overlay

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = overlay(REPO, REPO / "ambient-weather-mqtt" / "root" / "scripts")
FINALIZE = load(SCRIPTS / "finalize", "weather_finalize")


class ListenerTests(unittest.TestCase):
    def setUp(self):
        environ["TZ"] = "UTC"
        time.tzset()

    def test_other_path_is_bad_request_and_does_not_publish(self):
        started = []

        def start_response(code, headers):
            started.append((code, headers))

        with patch.object(FINALIZE, "publish") as send:
            body = FINALIZE.listener(
                {"PATH_INFO": "/ready", "HTTP_HOST": "station.local"},
                start_response,
            )

        self.assertEqual(body, [b""])
        self.assertEqual(
            started, [("400 Bad Request", [("Content-Type", "text/plain")])]
        )
        send.assert_not_called()

    def test_station_path_publishes_local_time_and_attributes(self):
        started = []

        def start_response(code, headers):
            started.append((code, headers))

        with patch.object(FINALIZE, "publish") as send:
            body = FINALIZE.listener(
                {
                    "PATH_INFO": (
                        "/AMBWeather/dateutc=2024-01-02 03:04:05&tempf=70.1&bar=1&bar=2"
                    ),
                    "HTTP_HOST": "station.local",
                },
                start_response,
            )

        self.assertEqual(body, [b""])
        self.assertEqual(started, [("200 OK", [("Content-Type", "text/plain")])])
        self.assertEqual(
            [call.args for call in send.call_args_list],
            [
                ("weather", "2024-01-02 03:04:05"),
                (
                    "weather/attributes",
                    json.dumps({"tempf": "70.1", "bar": ["1", "2"]}),
                ),
            ],
        )

    def test_convert_value_unwraps_one_item_and_keeps_many(self):
        self.assertEqual(FINALIZE.convert_value(["70.1"]), "70.1")
        self.assertEqual(FINALIZE.convert_value(["1", "2"]), ["1", "2"])

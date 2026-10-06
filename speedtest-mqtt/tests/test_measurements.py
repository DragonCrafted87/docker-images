import json
import unittest
from os import environ
from pathlib import Path
from unittest.mock import patch

from tests.load_scripts import load
from tests.load_scripts import overlay

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = overlay(REPO, REPO / "speedtest-mqtt" / "root" / "scripts")
JOB = load(SCRIPTS / "setup" / "run_job.py", "speedtest_job")


class MeasurementTests(unittest.TestCase):
    def test_percentile_uses_the_index_when_the_rank_is_whole(self):
        self.assertEqual(JOB.calculate_percentile([4, 1, 3, 2], 50), 3)

    def test_percentile_averages_neighbors_when_the_rank_is_fractional(self):
        self.assertEqual(JOB.calculate_percentile([4, 1, 3, 2], 90), 3.5)

    def test_download_success_returns_the_rate_and_waits(self):
        clocks = iter([10.0, 12.0])
        with patch.object(JOB, "requests_get", return_value=object()) as get:
            with patch.object(JOB, "sleep") as slept:
                with patch.object(JOB, "time", side_effect=lambda: next(clocks)):
                    result = JOB.download(200000)

        self.assertEqual(
            get.call_args.args[0], "https://speed.cloudflare.com/__down?bytes=200000"
        )
        slept.assert_called_once_with(JOB.SLEEP_BETWEEN_MEASUREMENTS)
        self.assertEqual(result, 1.0)

    def test_download_connection_error_returns_zero(self):
        with patch.object(
            JOB, "requests_get", side_effect=JOB.RequestsConnectionError("down")
        ):
            with patch.object(JOB, "sleep") as slept:
                result = JOB.download(1000)

        self.assertEqual(result, 0)
        slept.assert_not_called()

    def test_upload_success_posts_the_buffer(self):
        clocks = iter([1.0, 3.0])
        with patch.object(JOB, "requests_post", return_value=object()) as post:
            with patch.object(JOB, "sleep") as slept:
                with patch.object(JOB, "time", side_effect=lambda: next(clocks)):
                    result = JOB.upload(100000)

        self.assertEqual(post.call_args.args[0], "https://speed.cloudflare.com/__up")
        self.assertEqual(len(post.call_args.kwargs["data"]), 100000)
        slept.assert_called_once_with(JOB.SLEEP_BETWEEN_MEASUREMENTS)
        self.assertEqual(result, 0.5)

    def test_upload_connection_error_returns_zero(self):
        with patch.object(
            JOB, "requests_post", side_effect=JOB.RequestsConnectionError("up")
        ):
            with patch.object(JOB, "sleep") as slept:
                result = JOB.upload(1000)

        self.assertEqual(result, 0)
        slept.assert_not_called()

    def test_run_speed_test_walks_sizes_in_order(self):
        seen = []

        def operation(size):
            seen.append(size)
            return size

        result = JOB.run_speed_test([2, 1], operation)

        self.assertEqual(
            seen,
            [
                JOB.MEASUREMENT_SIZES[0],
                JOB.MEASUREMENT_SIZES[0],
                JOB.MEASUREMENT_SIZES[1],
            ],
        )
        self.assertEqual(result, seen)

    def test_ping_skips_empty_samples(self):
        samples = [None, 10.0, False, 30.0]

        def fake(host, unit):
            self.assertEqual(host, "cloudflare.com")
            self.assertEqual(unit, "ms")
            return samples.pop(0)

        with patch.dict(environ, {"PING_COUNT": "2"}):
            with patch.object(JOB, "ping", side_effect=fake):
                median_ping, jitter = JOB.calculate_ping()

        self.assertEqual(median_ping, 20.0)
        self.assertEqual(jitter, 20.0)

    def test_iteration_counts_use_the_default_or_the_environment(self):
        with patch.dict(environ, {}, clear=False):
            environ.pop("DOWNLOAD_ITERATIONS", None)
            environ.pop("UPLOAD_ITERATIONS", None)
            self.assertEqual(
                JOB.iteration_counts("DOWNLOAD_ITERATIONS", "10,8,6,4,2"),
                [10, 8, 6, 4, 2],
            )
            self.assertEqual(
                JOB.iteration_counts("UPLOAD_ITERATIONS", "8,6,4,2"), [8, 6, 4, 2]
            )

        with patch.dict(
            environ, {"DOWNLOAD_ITERATIONS": "2,1", "UPLOAD_ITERATIONS": "1"}
        ):
            self.assertEqual(
                JOB.iteration_counts("DOWNLOAD_ITERATIONS", "10,8,6,4,2"), [2, 1]
            )
            self.assertEqual(JOB.iteration_counts("UPLOAD_ITERATIONS", "8,6,4,2"), [1])

    def test_download_percentile_passes_iterations_to_the_run(self):
        with patch.dict(environ, {"DOWNLOAD_ITERATIONS": "2,1"}):
            with patch.object(JOB, "run_speed_test", return_value=[1, 2, 3, 4]) as run:
                result = JOB.calculate_download_percentile(50)

        self.assertEqual(run.call_args.args[0], [2, 1])
        self.assertIs(run.call_args.args[1], JOB.download)
        self.assertEqual(result, 3)

    def test_main_publishes_the_time_and_the_attributes(self):
        with patch.dict(environ, {"PERCENTILE": "95"}):
            with patch.object(JOB, "calculate_ping", return_value=(1.5, 0.25)) as ping:
                with patch.object(
                    JOB, "calculate_download_percentile", return_value=10
                ) as download:
                    with patch.object(
                        JOB, "calculate_upload_percentile", return_value=2
                    ) as upload:
                        with patch.object(JOB, "publish") as send:
                            with patch.object(JOB, "datetime") as clock:
                                clock.now.return_value.strftime.return_value = (
                                    "2024-01-02 03:04:05"
                                )
                                JOB.main()

        ping.assert_called_once_with()
        download.assert_called_once_with(95)
        upload.assert_called_once_with(95)
        self.assertEqual(
            send.call_args_list[0].args, ("speedtest", "2024-01-02 03:04:05")
        )
        self.assertEqual(send.call_args_list[1].args[0], "speedtest/attributes")
        self.assertEqual(
            json.loads(send.call_args_list[1].args[1]),
            {
                "median_ping": 1.5,
                "ping_jitter": 0.25,
                "download_mbps": 10,
                "upload_mbps": 2,
            },
        )

    def test_main_defaults_the_percentile_to_90(self):
        with patch.dict(environ, {}, clear=False):
            environ.pop("PERCENTILE", None)
            with patch.object(JOB, "calculate_ping", return_value=(1, 1)):
                with patch.object(
                    JOB, "calculate_download_percentile", return_value=1
                ) as download:
                    with patch.object(
                        JOB, "calculate_upload_percentile", return_value=1
                    ):
                        with patch.object(JOB, "publish"):
                            with patch.object(JOB, "datetime") as clock:
                                clock.now.return_value.strftime.return_value = (
                                    "2024-01-02 03:04:05"
                                )
                                JOB.main()

        download.assert_called_once_with(90)

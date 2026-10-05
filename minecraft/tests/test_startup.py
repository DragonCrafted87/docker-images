# pylint: disable=unused-argument
import importlib.util
import subprocess
import sys
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "root" / "scripts"
sys.path.insert(0, str(SCRIPTS))

# pylint: disable=wrong-import-position
from includes.fabric import fetch  # noqa: E402
from includes.fabric import release_version  # noqa: E402


def load_finalize(name="finalize"):
    path = str(SCRIPTS / "finalize")
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_file_location(name, path, loader=loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


FINALIZE = load_finalize()


class Response:
    def __init__(self, error=None, content=b"<ok>"):
        self.error = error
        self.content = content

    def raise_for_status(self):
        if self.error:
            raise self.error


class FetchTests(unittest.TestCase):
    def test_success_returns_without_retry(self):
        calls = []
        response = Response()

        def get(url, stream, timeout):
            calls.append((url, stream, timeout))
            return response

        slept = []
        logged = []
        result = fetch(
            "https://example.test/meta",
            get=get,
            sleep=slept.append,
            log=lambda *args: logged.append(args),
            attempts=5,
            timeout=(10, 60),
            transient=(OSError,),
        )

        self.assertIs(result, response)
        self.assertEqual(calls, [("https://example.test/meta", True, (10, 60))])
        self.assertEqual(slept, [])
        self.assertEqual(logged, [])

    def test_transient_then_success_waits_and_returns(self):
        response = Response()
        errors = [OSError("try again"), response]

        def get(url, stream, timeout):
            item = errors.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        slept = []
        logged = []
        result = fetch(
            "https://example.test/meta",
            get=get,
            sleep=slept.append,
            log=lambda *args: logged.append(args),
            attempts=5,
            transient=(OSError,),
        )

        self.assertIs(result, response)
        self.assertEqual(slept, [1])
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0][1], 1)
        self.assertEqual(logged[0][4], 1)

    def test_exhausted_transient_raises_last_error(self):
        first = OSError("first")
        second = OSError("second")
        errors = [first, second]

        def get(url, stream, timeout):
            raise errors.pop(0)

        slept = []
        logged = []
        with self.assertRaises(OSError) as caught:
            fetch(
                "https://example.test/meta",
                get=get,
                sleep=slept.append,
                log=lambda *args: logged.append(args),
                attempts=2,
                transient=(OSError,),
            )

        self.assertIs(caught.exception, second)
        self.assertEqual(slept, [1])
        self.assertEqual(len(logged), 1)

    def test_non_transient_error_is_not_retried(self):
        def get(url, stream, timeout):
            raise ValueError("metadata")

        slept = []
        with self.assertRaises(ValueError):
            fetch(
                "https://example.test/meta",
                get=get,
                sleep=slept.append,
                log=lambda *args: None,
                attempts=4,
                transient=(OSError,),
            )
        self.assertEqual(slept, [])

    def test_status_error_is_not_retried_when_it_is_not_transient(self):
        def get(url, stream, timeout):
            return Response(error=ValueError("500"))

        slept = []
        with self.assertRaises(ValueError):
            fetch(
                "https://example.test/meta",
                get=get,
                sleep=slept.append,
                log=lambda *args: None,
                attempts=3,
                transient=(OSError,),
            )
        self.assertEqual(slept, [])

    def test_delay_caps_at_thirty_seconds(self):
        response = Response()
        failures = 6

        def get(url, stream, timeout):
            nonlocal failures
            if failures:
                failures -= 1
                raise OSError("try again")
            return response

        slept = []
        fetch(
            "https://example.test/meta",
            get=get,
            sleep=slept.append,
            log=lambda *args: None,
            attempts=7,
            transient=(OSError,),
        )
        self.assertEqual(slept, [1, 2, 4, 8, 16, 30])

    def test_non_transient_after_a_retry_still_propagates(self):
        calls = {"n": 0}

        def get(url, stream, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("try again")
            raise RuntimeError("parse")

        slept = []
        with self.assertRaises(RuntimeError):
            fetch(
                "https://example.test/meta",
                get=get,
                sleep=slept.append,
                log=lambda *args: None,
                attempts=4,
                transient=(OSError,),
            )
        self.assertEqual(slept, [1])


class ReleaseVersionTests(unittest.TestCase):
    def test_release_string(self):
        metadata = {"metadata": {"versioning": {"release": "1.0.1"}}}
        self.assertEqual(release_version(metadata), "1.0.1")

    def test_missing_release_raises(self):
        with self.assertRaises(RuntimeError):
            release_version({"metadata": {"versioning": {}}})

    def test_empty_release_raises(self):
        with self.assertRaises(RuntimeError):
            release_version({"metadata": {"versioning": {"release": ""}}})

    def test_non_string_release_raises(self):
        with self.assertRaises(RuntimeError):
            release_version({"metadata": {"versioning": {"release": 1}}})

    def test_metadata_of_the_wrong_shape_raises(self):
        with self.assertRaises(RuntimeError):
            release_version(None)


class Server:
    def __init__(self, code):
        self.code = code
        self.stdin = Mock()
        self.killed = False

    def poll(self):
        return self.code

    def kill(self):
        self.killed = True


class Sync:
    def __init__(self, alive=False):
        self.alive = alive
        self.started = False
        self.killed = False

    def start(self):
        self.started = True

    def join(self, timeout=None):
        return None

    def is_alive(self):
        return self.alive

    def kill(self):
        self.killed = True


class ShutdownTests(unittest.TestCase):
    def test_signal_before_start_exits_without_sync(self):
        codes = []
        with patch.object(FINALIZE.LOGINFO, "close"), patch.object(
            FINALIZE.LOGERR, "close"
        ), patch.object(FINALIZE, "Process", side_effect=AssertionError("synced")):
            FINALIZE.shutdown(None, exit_fn=codes.append)
        self.assertEqual(codes, [0])

    def test_stopped_server_syncs_and_uses_its_code(self):
        server = Server(3)
        sync = Sync()
        codes = []
        with patch.object(FINALIZE.LOGINFO, "close"), patch.object(
            FINALIZE.LOGERR, "close"
        ), patch.object(FINALIZE, "Process", return_value=sync):
            FINALIZE.shutdown(server, exit_fn=codes.append)
        server.stdin.write.assert_not_called()
        self.assertTrue(sync.started)
        self.assertFalse(sync.killed)
        self.assertFalse(server.killed)
        self.assertEqual(codes, [3])

    def test_stop_that_finishes_uses_the_server_code(self):
        server = Server(None)
        polls = {"n": 0}

        def poll():
            polls["n"] += 1
            if polls["n"] == 1:
                return None
            return 4

        server.poll = poll
        sync = Sync()
        codes = []

        def watch(*_values):
            FINALIZE.LOGINFO.watched_value_found = True

        with patch.object(FINALIZE.LOGINFO, "close"), patch.object(
            FINALIZE.LOGERR, "close"
        ), patch.object(FINALIZE, "Process", return_value=sync), patch.object(
            FINALIZE.LOGINFO, "watch_for_value", side_effect=watch
        ), patch.object(
            FINALIZE, "sleep"
        ):
            FINALIZE.shutdown(server, exit_fn=codes.append)
        server.stdin.write.assert_called_with(b"stop\n")
        self.assertFalse(server.killed)
        self.assertEqual(codes, [4])

    def test_running_server_is_stopped_and_killed_if_it_stays_up(self):
        server = Server(None)
        sync = Sync()
        codes = []

        def watch(*_values):
            FINALIZE.LOGINFO.watched_value_found = True

        with patch.object(FINALIZE.LOGINFO, "close"), patch.object(
            FINALIZE.LOGERR, "close"
        ), patch.object(FINALIZE, "Process", return_value=sync), patch.object(
            FINALIZE.LOGINFO, "watch_for_value", side_effect=watch
        ), patch.object(
            FINALIZE, "sleep"
        ):
            FINALIZE.shutdown(server, exit_fn=codes.append)
        server.stdin.write.assert_called_with(b"stop\n")
        self.assertTrue(server.killed)
        self.assertEqual(codes, [9999])

    def test_sync_timeout_kills_the_copy_and_still_exits(self):
        server = Server(0)
        sync = Sync(alive=True)
        codes = []
        with patch.object(FINALIZE.LOGINFO, "close"), patch.object(
            FINALIZE.LOGERR, "close"
        ), patch.object(FINALIZE, "Process", return_value=sync):
            FINALIZE.shutdown(server, exit_fn=codes.append)
        self.assertTrue(sync.killed)
        self.assertEqual(codes, [0])

    def test_failure_before_start_exits_1(self):
        codes = []
        with patch.object(FINALIZE.LOGINFO, "close"), patch.object(
            FINALIZE.LOGERR, "close"
        ), patch.object(FINALIZE, "shutdown", side_effect=AssertionError("shutdown")):
            FINALIZE.exit_after_failure(None, exit_fn=codes.append)
        self.assertEqual(codes, [1])

    def test_failure_after_start_shuts_the_server_down(self):
        server = Server(0)
        seen = []

        def record(process, exit_fn=None):
            seen.append((process, exit_fn))

        with patch.object(FINALIZE, "shutdown", side_effect=record):
            FINALIZE.exit_after_failure(server, exit_fn=seen.append)
        self.assertEqual(seen[0][0], server)

    def test_signal_handler_shuts_down_the_current_child(self):
        sentinel = object()
        seen = []
        FINALIZE.CHILD_PROCESS = sentinel
        with patch.object(FINALIZE, "shutdown", side_effect=seen.append):
            FINALIZE.signal_handler(15, None)
        self.assertEqual(seen, [sentinel])
        FINALIZE.CHILD_PROCESS = None


class ProcessExitTests(unittest.TestCase):
    def test_log_pipes_do_not_keep_the_interpreter_alive(self):
        script = (
            "import importlib.util\n"
            "import sys\n"
            "from importlib.machinery import SourceFileLoader\n"
            f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
            f"path = {str(SCRIPTS / 'finalize')!r}\n"
            "loader = SourceFileLoader('finalize_child', path)\n"
            "spec = importlib.util.spec_from_file_location(\n"
            "    'finalize_child', path, loader=loader)\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "loader.exec_module(module)\n"
            "print('LOADED', flush=True)\n"
            "raise SystemExit(1)\n"
        )
        try:
            completed = subprocess.run(
                [sys.executable, "-c", script],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired as error:
            self.fail(f"interpreter stayed up after the main thread exited: {error}")

        self.assertIn("LOADED", completed.stdout)
        self.assertEqual(completed.returncode, 1)
        self.assertTrue(FINALIZE.LOGINFO.daemon)
        self.assertTrue(FINALIZE.LOGERR.daemon)


if __name__ == "__main__":
    unittest.main()

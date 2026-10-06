# pylint: disable=unused-argument
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

from tests.load_scripts import load
from tests.load_scripts import overlay

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = overlay(REPO, REPO / "minecraft" / "root" / "scripts")

# pylint: disable=wrong-import-order,wrong-import-position,no-name-in-module
from includes.fabric import fetch  # noqa: E402
from includes.fabric import release_version  # noqa: E402

FINALIZE = load(SCRIPTS / "finalize", "finalize")


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


class HeapTests(unittest.TestCase):
    def limit(self, files, free_kb):
        def read_text(path):
            return files.get(path)

        return FINALIZE.memory_limit_kb(read_text, lambda: free_kb)

    def test_cgroup_v2_bytes_win_over_v1_and_host(self):
        files = {
            FINALIZE.CGROUP_V2_MAX: "536870912\n",
            FINALIZE.CGROUP_V1_LIMIT: "999\n",
        }
        self.assertEqual(self.limit(files, 63146052), 536870912 // 1024)

    def test_v2_max_uses_a_finite_v1_limit(self):
        files = {
            FINALIZE.CGROUP_V2_MAX: "max\n",
            FINALIZE.CGROUP_V1_LIMIT: "2147483648\n",
        }
        self.assertEqual(self.limit(files, 100), 2147483648 // 1024)

    def test_unlimited_v1_falls_back_to_free(self):
        files = {FINALIZE.CGROUP_V1_LIMIT: str(FINALIZE.UNLIMITED_CGROUP_BYTES)}
        self.assertEqual(self.limit(files, 63146052), 63146052)

    def test_missing_cgroup_files_fall_back_to_free(self):
        self.assertEqual(self.limit({}, 63146052), 63146052)

    def test_v2_max_without_v1_falls_back_to_free(self):
        self.assertEqual(self.limit({FINALIZE.CGROUP_V2_MAX: "max"}, 4000000), 4000000)

    def test_host_sized_heap_matches_the_old_quarter(self):
        self.assertEqual(FINALIZE.heap_gigabytes(63146052), 15)

    def test_quarter_under_one_gigabyte_floors_at_one(self):
        self.assertEqual(FINALIZE.heap_gigabytes(1_000_000), 1)
        self.assertEqual(FINALIZE.heap_gigabytes(3_000_000), 1)

    def test_four_gigabytes_is_one_and_eight_is_two(self):
        self.assertEqual(FINALIZE.heap_gigabytes(4_000_000), 1)
        self.assertEqual(FINALIZE.heap_gigabytes(8_000_000), 2)

    def test_under_one_gigabyte_refuses_to_start(self):
        with self.assertRaises(RuntimeError):
            FINALIZE.heap_gigabytes(999_999)

    def test_start_uses_the_cgroup_heap_and_does_not_call_free(self):
        def read_text(path):
            if path == FINALIZE.CGROUP_V2_MAX:
                return "8589934592\n"
            return None

        with patch.object(FINALIZE, "chdir"), patch.object(
            FINALIZE, "read_cgroup_text", side_effect=read_text
        ), patch.object(FINALIZE, "free_total_kb") as free, patch.object(
            FINALIZE, "Popen", return_value=Mock()
        ) as popen:
            FINALIZE.start_minecraft(False)

        free.assert_not_called()
        command = popen.call_args.args[0]
        self.assertIn("-Xmx2G", command)
        self.assertIn("-Xms2G", command)

    def test_start_refuses_before_launching_java(self):
        with patch.object(FINALIZE, "chdir"), patch.object(
            FINALIZE, "memory_limit_kb", return_value=512 * 1024
        ), patch.object(FINALIZE, "Popen") as popen:
            with self.assertRaises(RuntimeError):
                FINALIZE.start_minecraft(False)

        popen.assert_not_called()


class CopyTests(unittest.TestCase):
    def test_directory_copy_creates_the_target_and_purges(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ram = root / "ram"
            nfs = root / "nfs"
            (ram / "world").mkdir(parents=True)
            (ram / "world" / "keep.txt").write_text("new", encoding="utf-8")
            with patch.object(FINALIZE, "RAM_DRIVE", f"{ram}/"), patch.object(
                FINALIZE, "NFS_DRIVE", f"{nfs}/"
            ):
                FINALIZE.copy_directory_to_storage("world")
                self.assertEqual(
                    (nfs / "world" / "keep.txt").read_text(encoding="utf-8"), "new"
                )
                (nfs / "world" / "stale.txt").write_text("old", encoding="utf-8")
                FINALIZE.copy_directory_to_storage("world")
            self.assertFalse((nfs / "world" / "stale.txt").exists())
            self.assertTrue((nfs / "world" / "keep.txt").exists())

    def test_missing_source_is_not_swallowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(FINALIZE, "RAM_DRIVE", f"{root / 'ram'}/"), patch.object(
                FINALIZE, "NFS_DRIVE", f"{root / 'nfs'}/"
            ):
                with self.assertRaises(ValueError):
                    FINALIZE.copy_directory_to_storage("world")

    def test_file_list_drops_a_removed_file_and_keeps_the_world(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ram = root / "ram"
            nfs = root / "nfs"
            ram.mkdir()
            (nfs / "world").mkdir(parents=True)
            (nfs / "server.properties").write_text("motd=old\n", encoding="utf-8")
            (nfs / "whitelist.json").write_text("[]\n", encoding="utf-8")
            (nfs / "world" / "region.mca").write_text("chunk", encoding="utf-8")
            fresh = ram / "server.properties"
            fresh.write_text("motd=new\n", encoding="utf-8")
            os.utime(fresh, (fresh.stat().st_atime, fresh.stat().st_mtime + 5))
            with patch.object(FINALIZE, "RAM_DRIVE", f"{ram}/"), patch.object(
                FINALIZE, "NFS_DRIVE", f"{nfs}/"
            ):
                FINALIZE.copy_files_to_storage()
            self.assertEqual(
                (nfs / "server.properties").read_text(encoding="utf-8"), "motd=new\n"
            )
            self.assertFalse((nfs / "whitelist.json").exists())
            self.assertEqual(
                (nfs / "world" / "region.mca").read_text(encoding="utf-8"), "chunk"
            )


class EulaTests(unittest.TestCase):
    def test_eula_is_persisted(self):
        self.assertIn("eula.txt", FINALIZE.FILE_LIST)

    def test_eula_true_writes_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(FINALIZE, "RAM_DRIVE", f"{tmp}/"), patch.dict(
                os.environ, {"EULA": "true"}
            ):
                FINALIZE.accept_eula()
            text = (Path(tmp) / "eula.txt").read_text(encoding="utf-8")
        self.assertIn("eula=true\n", text)

    def test_unset_eula_leaves_the_ramdisk_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(FINALIZE, "RAM_DRIVE", f"{tmp}/"), patch.dict(
                os.environ, {}, clear=False
            ):
                os.environ.pop("EULA", None)
                FINALIZE.accept_eula()
            self.assertFalse((Path(tmp) / "eula.txt").exists())


class StartupTests(unittest.TestCase):
    def tearDown(self):
        FINALIZE.CHILD_PROCESS = None
        FINALIZE.LOGINFO.watched_value_found = False

    def run_main(self, process, watch):
        store = Path(tempfile.mkdtemp()) / "store.pckl"
        codes = []
        with patch.object(FINALIZE, "DATA_STORE", str(store)), patch.object(
            FINALIZE, "signal"
        ), patch.object(FINALIZE, "install_fabric"), patch.object(
            FINALIZE, "sync_copy"
        ), patch.object(
            FINALIZE, "accept_eula"
        ), patch.object(
            FINALIZE, "start_minecraft", return_value=process
        ), patch.object(
            FINALIZE, "sleep"
        ), patch.object(
            FINALIZE.LOGINFO, "watch_for_value", side_effect=watch
        ), patch.object(
            FINALIZE.LOGINFO, "close"
        ), patch.object(
            FINALIZE.LOGERR, "close"
        ), patch.object(
            FINALIZE, "shutdown"
        ) as shutdown, patch.object(
            FINALIZE, "exit_now", side_effect=codes.append
        ), patch.dict(
            "os.environ", {"MINECRAFT_VERSION": "1.19.2"}
        ):
            FINALIZE.main()
        return store, codes, shutdown

    def test_exit_before_rcon_does_not_record_or_copy(self):
        process = Server(1)

        def watch(*_values):
            FINALIZE.LOGINFO.watched_value_found = False

        store, codes, shutdown = self.run_main(process, watch)

        self.assertEqual(codes, [1])
        self.assertFalse(store.exists())
        shutdown.assert_not_called()

    def test_ready_server_records_the_version(self):
        process = Server(None)
        polls = {"n": 0}

        def poll():
            polls["n"] += 1
            if polls["n"] == 1:
                return None
            return 0

        process.poll = poll

        def watch(*values):
            FINALIZE.LOGINFO.watched_value_found = values[0] == "RCON running"

        store, codes, shutdown = self.run_main(process, watch)

        self.assertEqual(codes, [])
        self.assertTrue(store.exists())
        shutdown.assert_called_once()

    def test_upgrade_still_running_does_not_record_the_version(self):
        process = Server(None)
        polls = {"n": 0}

        def poll():
            polls["n"] += 1
            if polls["n"] <= FINALIZE.SAVE_INTERVAL + 2:
                return None
            return 0

        process.poll = poll

        def watch(*_values):
            FINALIZE.LOGINFO.watched_value_found = False

        store, _codes, shutdown = self.run_main(process, watch)

        self.assertFalse(store.exists())
        shutdown.assert_called_once()

    def test_clean_exit_before_rcon_is_still_a_failure(self):
        process = Server(0)

        def watch(*_values):
            return None

        _store, codes, shutdown = self.run_main(process, watch)

        self.assertEqual(codes, [1])
        shutdown.assert_not_called()


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
    def __init__(self, alive=False, exitcode=0):
        self.alive = alive
        self.exitcode = exitcode
        self.started = False
        self.killed = False
        self.timeout = None

    def start(self):
        self.started = True

    def join(self, timeout=None):
        self.timeout = timeout

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

    def test_failed_copy_does_not_exit_clean(self):
        server = Server(0)
        sync = Sync(exitcode=1)
        codes = []
        with patch.object(FINALIZE.LOGINFO, "close"), patch.object(
            FINALIZE.LOGERR, "close"
        ), patch.object(FINALIZE, "Process", return_value=sync):
            FINALIZE.shutdown(server, exit_fn=codes.append)
        self.assertFalse(sync.killed)
        self.assertEqual(codes, [1])

    def test_failed_save_stops_instead_of_resuming(self):
        server = Server(None)
        sync = Sync(exitcode=1)

        def watch(*_values):
            FINALIZE.LOGINFO.watched_value_found = True

        with patch.object(FINALIZE, "Process", return_value=sync), patch.object(
            FINALIZE.LOGINFO, "watch_for_value", side_effect=watch
        ), patch.object(FINALIZE, "sleep"):
            FINALIZE.save(server)

        writes = [call.args[0] for call in server.stdin.write.call_args_list]
        self.assertIn(b"stop\n", writes)
        self.assertNotIn(b"save-on\n", writes)

    def test_sync_timeout_kills_the_copy_and_still_exits(self):
        server = Server(0)
        sync = Sync(alive=True)
        codes = []
        with patch.object(FINALIZE.LOGINFO, "close"), patch.object(
            FINALIZE.LOGERR, "close"
        ), patch.object(FINALIZE, "Process", return_value=sync):
            FINALIZE.shutdown(server, exit_fn=codes.append)
        self.assertTrue(sync.killed)
        self.assertEqual(codes, [1])

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
        FINALIZE.SHUTTING_DOWN = False
        with patch.object(FINALIZE, "shutdown", side_effect=seen.append):
            FINALIZE.signal_handler(15, None)
        self.assertEqual(seen, [sentinel])
        FINALIZE.CHILD_PROCESS = None
        FINALIZE.SHUTTING_DOWN = False

    def test_second_signal_exits_without_another_shutdown(self):
        FINALIZE.SHUTTING_DOWN = False
        FINALIZE.CHILD_PROCESS = Server(0)
        codes = []

        def stop(code):
            codes.append(code)
            raise SystemExit(code)

        with patch.object(FINALIZE, "shutdown"):
            FINALIZE.signal_handler(15, None)
        with patch.object(
            FINALIZE, "shutdown", side_effect=AssertionError("second shutdown")
        ), patch.object(FINALIZE, "exit_now", side_effect=stop):
            with self.assertRaises(SystemExit):
                FINALIZE.signal_handler(15, None)
        self.assertEqual(codes, [1])
        FINALIZE.CHILD_PROCESS = None
        FINALIZE.SHUTTING_DOWN = False

    def test_broken_pipe_still_copies_and_exits(self):
        server = Server(None)
        state = {"broke": False}

        def poll():
            if state["broke"]:
                return 0
            return None

        def write(_line):
            state["broke"] = True
            raise BrokenPipeError

        server.poll = poll
        server.stdin.write.side_effect = write
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

        self.assertTrue(sync.started)
        self.assertEqual(sync.timeout, FINALIZE.COPY_TIMEOUT_SECONDS)
        self.assertEqual(codes, [0])

    def test_stop_wait_is_capped_at_the_grace_budget(self):
        server = Server(None)
        sync = Sync()
        sleeps = []

        def watch(*_values):
            FINALIZE.LOGINFO.watched_value_found = False

        with patch.object(FINALIZE.LOGINFO, "close"), patch.object(
            FINALIZE.LOGERR, "close"
        ), patch.object(FINALIZE, "Process", return_value=sync), patch.object(
            FINALIZE.LOGINFO, "watch_for_value", side_effect=watch
        ), patch.object(
            FINALIZE, "sleep", side_effect=sleeps.append
        ):
            FINALIZE.shutdown(server, exit_fn=lambda _code: None)

        self.assertEqual(len(sleeps), FINALIZE.STOP_WAIT_SECONDS)
        self.assertEqual(sync.timeout, FINALIZE.COPY_TIMEOUT_SECONDS)
        self.assertEqual(
            FINALIZE.STOP_GRACE_SECONDS,
            FINALIZE.STOP_WAIT_SECONDS + FINALIZE.COPY_TIMEOUT_SECONDS + 10,
        )


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

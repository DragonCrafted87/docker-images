import importlib.util
import unittest
from importlib.machinery import SourceFileLoader
from os import environ
from pathlib import Path
from tempfile import TemporaryDirectory

INIT_PATH = Path(__file__).resolve().parents[1] / "root" / "docker_service_init"


def load_init():
    path = str(INIT_PATH)
    loader = SourceFileLoader("docker_service_init", path)
    spec = importlib.util.spec_from_file_location(
        "docker_service_init", path, loader=loader
    )
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


INIT = load_init()


class SetupTests(unittest.TestCase):
    def test_scripts_run_in_name_order(self):
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for name in ("c.py", "a.py", "b.py", "__init__.py"):
                (directory / name).write_text("", encoding="utf-8")
            (directory / "subdir").mkdir()
            ran = []

            def run_script(path):
                ran.append(path.name)
                return 0

            selected = []
            status = INIT.start(
                ["init"],
                directory,
                "/scripts/finalize",
                run_script,
                lambda program, argv: selected.append((program, argv)),
            )

        self.assertEqual(ran, ["a.py", "b.py", "c.py"])
        self.assertEqual(status, 0)
        self.assertEqual(selected, [("/scripts/finalize", ["finalize"])])

    def test_failed_setup_skips_finalize_and_returns_status(self):
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for name in ("01.py", "02.py", "03.py"):
                (directory / name).write_text("", encoding="utf-8")
            ran = []

            def run_script(path):
                ran.append(path.name)
                if path.name == "02.py":
                    return 4
                return 0

            selected = []
            status = INIT.start(
                ["init"],
                directory,
                "/scripts/finalize",
                run_script,
                lambda program, argv: selected.append(program),
            )

        self.assertEqual(status, 4)
        self.assertEqual(ran, ["01.py", "02.py"])
        self.assertEqual(selected, [])

    def test_empty_setup_selects_finalize(self):
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "__init__.py").write_text("", encoding="utf-8")
            selected = []
            status = INIT.start(
                ["init", "--flag"],
                directory,
                "/scripts/finalize",
                lambda path: 0,
                lambda program, argv: selected.append((program, argv)),
            )

        self.assertEqual(status, 0)
        self.assertEqual(selected, [("/scripts/finalize", ["finalize", "--flag"])])
        self.assertEqual(environ["PYTHONPATH"], "/scripts:/scripts/includes")

import importlib.util
import shutil
import sys
import tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path


def overlay(repo, image_scripts):
    """Base scripts, with one image's scripts copied over them."""
    dest = Path(tempfile.mkdtemp(prefix="image-scripts-")) / "scripts"
    shutil.copytree(Path(repo) / "base" / "root" / "scripts", dest)
    image_scripts = Path(image_scripts)
    for path in image_scripts.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        target = dest / path.relative_to(image_scripts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    if str(dest) not in sys.path:
        sys.path.insert(0, str(dest))
    return dest


def load(path, name):
    path = str(path)
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_file_location(name, path, loader=loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module

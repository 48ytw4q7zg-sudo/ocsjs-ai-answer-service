"""Portable application paths, independent of the current working directory."""
from pathlib import Path
import sys

_root = None
_data = None


def activate(root=None, data=None):
    global _root, _data
    _root = Path(root).resolve() if root is not None else application_root()
    _data = Path(data).resolve() if data is not None else _root / 'data'


def is_portable():
    return bool(getattr(sys, 'frozen', False) or _root is not None)


def application_root():
    if _root is not None:
        return _root
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def data_root():
    return _data if _data is not None else application_root() / 'data'


def resource_path(name):
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return root / name

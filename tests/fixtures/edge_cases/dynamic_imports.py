"""Module with dynamic imports via importlib."""
import importlib


def load_plugin(name: str):
    module = importlib.import_module(name)
    return module


def load_with_spec(path: str):
    spec = importlib.util.spec_from_file_location("dynamic_module", path)
    mod = importlib.util.module_from_spec(spec)
    return mod

"""Timed movement control for the Raspberry Pi robot."""


def _legacy_entry(name, target):
    """Run an old script name, or alias its import to the canonical module."""
    import importlib
    import sys

    module = importlib.import_module(target)
    if name == "__main__":
        raise SystemExit(module.main())
    sys.modules[name] = module

"""Compatibility entry point; implementation: connections.bluetooth.client."""

from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehicle_testing import _legacy_entry

_legacy_entry(__name__, "vehicle_testing.connections.bluetooth.client")

"""Shared resources are relative to the package, not the process directory."""

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLE = PACKAGE_ROOT / "examples" / "scratch_sample.txt"

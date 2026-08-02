"""Guarantees the repo root is on sys.path so tests can import root-level
modules (audit_tools, snapshot, comparar) directly, regardless of the
directory or import-mode pytest is invoked with.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

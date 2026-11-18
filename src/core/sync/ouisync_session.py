"""Load the pinned upstream Ouisync Python session binding from the app bundle."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_vendor_python_path() -> Path:
    """Make bundled Python packages importable in source and packaged layouts."""
    module_path = Path(__file__).resolve()
    for parent in module_path.parents:
        vendor_path = parent / "vendor" / "python"
        if vendor_path.is_dir():
            value = str(vendor_path)
            if value not in sys.path:
                sys.path.insert(0, value)
            return vendor_path
    raise FileNotFoundError("bundled_python_packages_missing")


def load_session_api():
    """Import the upstream session API after adding its bundled dependencies."""
    ensure_vendor_python_path()
    from ouisync import session

    return session

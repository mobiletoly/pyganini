"""Explicit application-owned development entrypoint."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

__all__ = ["ROOT", "_MODULE"]

ROOT = Path(__file__).resolve().parent
_PATH = ROOT.parent / "dev_support.py"
_SPEC = importlib.util.spec_from_file_location("dev_support", _PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Cannot load example supervisor: {_PATH}")
if TYPE_CHECKING:
    import dev_support as _MODULE
else:
    _MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

if __name__ == "__main__":
    raise SystemExit(_MODULE.main(ROOT, "app.main:create_development_app"))
